#!/usr/bin/env bash
#
# dev.sh — Lexicon launcher. Menu-driven: build, preview, or dev mode.
#
# Usage:  ./dev.sh
# Stop:   Ctrl+C (kills all services)
#

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/lexicon-backend"
FRONTEND="$ROOT/lexicon-frontend"
SHELL_SVC="$ROOT/lexicon-shell"

# ── Ports (single source of truth) ──────────────────────────────
HTTP_PORT=8000          # Brain HTTP REST API
WS_PORT=8000            # Brain WebSocket (/ws) — same server as HTTP
SHELL_WS_PORT=8765      # Shell microservice PTY WebSocket
SPINE_PUSH_PORT=5557    # ZeroMQ PUSH→PULL (external → Brain)
SPINE_PUB_PORT=5556     # ZeroMQ PUB (Brain → subscribers)
VITE_DEV_PORT=1420      # Vite dev server (dev mode only)
VITE_HMR_PORT=1421      # Vite HMR WebSocket (dev mode only)

# ensure bun + cargo are in PATH
export PATH="$HOME/.bun/bin:$HOME/.cargo/bin:$PATH"

# ────────────────────────────────────────────────────────────────
# Helper: print the full info banner
# ────────────────────────────────────────────────────────────────
print_banner() {
  local mode="$1"
  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  printf  "║  %-60s║\n" "Lexicon is running  [$mode]"
  echo "╠══════════════════════════════════════════════════════════════╣"
  echo "║                                                              ║"
  echo "║  SERVICES                                                    ║"
  printf  "║    Brain HTTP API  →  http://localhost:%-22s║\n" "$HTTP_PORT"
  printf  "║    Brain WebSocket →  ws://localhost:$WS_PORT/ws%-19s║\n" ""
  printf  "║    Shell PTY WS    →  ws://localhost:%-22s║\n" "$SHELL_WS_PORT"
  printf  "║    Spine PUSH      →  tcp://127.0.0.1:%-21s║\n" "$SPINE_PUSH_PORT  (write commands here)"
  printf  "║    Spine PUB       →  tcp://127.0.0.1:%-21s║\n" "$SPINE_PUB_PORT   (subscribe to events)"
  if [ "$mode" = "DEV" ]; then
  printf  "║    Vite Dev Server →  http://localhost:%-21s║\n" "$VITE_DEV_PORT"
  printf  "║    Vite HMR WS     →  ws://localhost:%-22s║\n"  "$VITE_HMR_PORT"
  fi
  echo "║                                                              ║"
  echo "╠══════════════════════════════════════════════════════════════╣"
  echo "║                                                              ║"
  echo "║  TOGGLE / WINDOW                                             ║"
  echo "║    Script:    ./lexicon-toggle                               ║"
  echo "║    Hotkey:    Bind lexicon-toggle to Super+\` in your DE     ║"
  echo "║    Terminal:  Ctrl+\` inside Lexicon to toggle terminal       ║"
  echo "║                                                              ║"
  echo "╠══════════════════════════════════════════════════════════════╣"
  echo "║                                                              ║"
  echo "║  CURL QUICK-REFERENCE                                        ║"
  echo "║                                                              ║"
  echo "║  # Health check                                              ║"
  echo "║  curl http://localhost:8000/health                           ║"
  echo "║                                                              ║"
  echo "║  # Toggle overlay visibility                                 ║"
  echo "║  curl -X POST http://localhost:8000/toggle                   ║"
  echo "║                                                              ║"
  echo "║  # System stats (CPU / RAM / disk / uptime)                  ║"
  echo "║  curl http://localhost:8000/system                           ║"
  echo "║                                                              ║"
  echo "║  # WhatsApp — get chats / contacts                           ║"
  echo "║  curl http://localhost:8000/whatsapp/chats                   ║"
  echo "║  curl http://localhost:8000/whatsapp/contacts                ║"
  echo "║                                                              ║"
  echo "║  # WhatsApp — get messages (all or by contact)               ║"
  echo "║  curl http://localhost:8000/whatsapp/messages                ║"
  echo "║  curl 'http://localhost:8000/whatsapp/messages?contact=Alice'║"
  echo "║                                                              ║"
  echo "║  # WhatsApp — push a message                                 ║"
  echo "║  curl -X POST http://localhost:8000/whatsapp/message \\       ║"
  echo "║    -H 'Content-Type: application/json' \\                     ║"
  echo "║    -d '{\"contact\":\"Alice\",\"text\":\"Hello\"}'                  ║"
  echo "║                                                              ║"
  echo "║  # WhatsApp — connection status                              ║"
  echo "║  curl http://localhost:8000/whatsapp/status                  ║"
  echo "║                                                              ║"
  echo "║  # Spine — push a toggle event via ZeroMQ                    ║"
  echo "║  python3 -c \"                                                ║"
  echo "║    import zmq, json; c=zmq.Context();                        ║"
  echo "║    s=c.socket(zmq.PUSH); s.connect('tcp://127.0.0.1:5557');  ║"
  echo "║    s.send_json({'channel':'lexicon/toggle','payload':'{}'})\" ║"
  echo "║                                                              ║"
  echo "║  # WebSocket — interactive test (requires wscat / websocat)  ║"
  echo "║  wscat -c ws://localhost:8000/ws                             ║"
  echo "║  websocat ws://localhost:8000/ws                             ║"
  echo "║                                                              ║"
  echo "╠══════════════════════════════════════════════════════════════╣"
  echo "║  Ctrl+C to stop everything                                   ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
}

# ────────────────────────────────────────────────────────────────
# Helper: ensure shell microservice venv exists
# ────────────────────────────────────────────────────────────────
ensure_shell_venv() {
  if [ ! -d "$SHELL_SVC/.venv" ]; then
    echo "  [setup] Creating shell microservice venv..."
    cd "$SHELL_SVC"
    uv venv .venv
    .venv/bin/pip install websockets
    echo "  [setup] Done."
  fi
}

# ────────────────────────────────────────────────────────────────
# Helper: kill stale processes on our ports
# ────────────────────────────────────────────────────────────────
kill_stale() {
  echo "  [cleanup] Killing stale processes..."
  kill "$(lsof -ti :$HTTP_PORT)"   2>/dev/null || true
  kill "$(lsof -ti :$SHELL_WS_PORT)" 2>/dev/null || true
  pkill -x lexicon-frontend         2>/dev/null || true
  sleep 0.5
}

# ────────────────────────────────────────────────────────────────
# Helper: start the always-on backend services
#   - Shell microservice (:8765)
#   - Brain / FastAPI    (:8000)
# ────────────────────────────────────────────────────────────────
start_backend_services() {
  echo "  [shell]   Starting PTY shell microservice on :$SHELL_WS_PORT..."
  cd "$SHELL_SVC"
  .venv/bin/python shell_server.py &
  SHELL_PID=$!

  echo "  [brain]   Starting Brain + Spine on :$HTTP_PORT..."
  cd "$BACKEND"
  .venv/bin/uvicorn src.main:app --host 0.0.0.0 --port "$HTTP_PORT" --reload &
  BACK_PID=$!
}

# ────────────────────────────────────────────────────────────────
# Cleanup trap — kills everything on exit / Ctrl+C
# ────────────────────────────────────────────────────────────────
TAURI_PID=""
BACK_PID=""
SHELL_PID=""
VITE_PID=""

cleanup() {
  echo ""
  echo "  Stopping Lexicon..."
  [ -n "$TAURI_PID" ]  && kill "$TAURI_PID"  2>/dev/null || true
  [ -n "$VITE_PID"  ]  && kill "$VITE_PID"   2>/dev/null || true
  [ -n "$BACK_PID"  ]  && kill "$BACK_PID"   2>/dev/null || true
  [ -n "$SHELL_PID" ]  && kill "$SHELL_PID"  2>/dev/null || true
  if [ -f /tmp/lexicon-whatsapp.pid ]; then
    kill "$(cat /tmp/lexicon-whatsapp.pid)" 2>/dev/null || true
    rm -f /tmp/lexicon-whatsapp.pid
  fi
  [ -n "$TAURI_PID" ]  && wait "$TAURI_PID"  2>/dev/null || true
  [ -n "$VITE_PID"  ]  && wait "$VITE_PID"   2>/dev/null || true
  [ -n "$BACK_PID"  ]  && wait "$BACK_PID"   2>/dev/null || true
  [ -n "$SHELL_PID" ]  && wait "$SHELL_PID"  2>/dev/null || true
  echo "  Done."
}
trap cleanup EXIT INT TERM

# ════════════════════════════════════════════════════════════════
# MENU
# ════════════════════════════════════════════════════════════════
echo ""
echo "  ╭──────────────────────────────────╮"
echo "  │        Lexicon Launcher          │"
echo "  ├──────────────────────────────────┤"
echo "  │  1)  Build  (Svelte + Tauri)     │"
echo "  │  2)  Preview  (run built binary) │"
echo "  │  3)  Dev  (Vite hot-reload)      │"
echo "  ╰──────────────────────────────────╯"
echo ""
read -rp "  Choose [1/2/3]: " CHOICE
echo ""

case "$CHOICE" in

  # ──────────────────────────────────────────────────────────────
  # 1 — BUILD
  # ──────────────────────────────────────────────────────────────
  1)
    echo "═══ BUILD MODE ═══════════════════════════════════════════════"

    echo "[1/4] Building Svelte frontend..."
    cd "$FRONTEND"
    bun run build
    echo "   Done: Svelte build"

    echo "[2/4] Building Tauri release binary..."
    cd "$FRONTEND"
    bun run tauri build 2>&1 | tail -5
    echo "   Done: binary → src-tauri/target/release/lexicon-frontend"

    kill_stale
    ensure_shell_venv
    start_backend_services

    echo "[3/4] Starting Tauri client (hidden until toggled)..."
    sleep 1
    "$FRONTEND/src-tauri/target/release/lexicon-frontend" &
    TAURI_PID=$!

    echo "[4/4] All services up."
    print_banner "BUILD → RUN"
    ;;

  # ──────────────────────────────────────────────────────────────
  # 2 — PREVIEW (run existing release binary, no rebuild)
  # ──────────────────────────────────────────────────────────────
  2)
    echo "═══ PREVIEW MODE ═════════════════════════════════════════════"
    BINARY="$FRONTEND/src-tauri/target/release/lexicon-frontend"
    if [ ! -f "$BINARY" ]; then
      echo "  ✗ No release binary found at:"
      echo "      $BINARY"
      echo "  Run option 1 (Build) first."
      exit 1
    fi

    kill_stale
    ensure_shell_venv
    start_backend_services

    echo "  [tauri]  Starting Tauri client (hidden until toggled)..."
    sleep 1
    "$BINARY" &
    TAURI_PID=$!

    echo "  All services up."
    print_banner "PREVIEW"
    ;;

  # ──────────────────────────────────────────────────────────────
  # 3 — DEV (Vite hot-reload + tauri dev)
  # ──────────────────────────────────────────────────────────────
  3)
    echo "═══ DEV MODE ═════════════════════════════════════════════════"

    kill_stale
    ensure_shell_venv
    start_backend_services

    echo "  [vite]   Starting Vite dev server on :$VITE_DEV_PORT..."
    cd "$FRONTEND"
    bun run dev &
    VITE_PID=$!

    echo "  [tauri]  Starting Tauri in dev mode (waits for Vite)..."
    sleep 2
    bun run tauri dev &
    TAURI_PID=$!

    echo "  All services up."
    print_banner "DEV"
    ;;

  *)
    echo "  Invalid choice. Exiting."
    exit 1
    ;;
esac

wait
