#!/usr/bin/env bash
#
# dev.sh — build everything, start backend (+ Spine) + Tauri client.
# Both run persistently. Press Super+` to toggle (bind lexicon-toggle to your DE shortcut).
#
# Usage:  ./dev.sh
# Stop:   Ctrl+C (kills both backend and Tauri)
#

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/lexicon-backend"
FRONTEND="$ROOT/lexicon-frontend"
SHELL_SVC="$ROOT/lexicon-shell"

# ensure bun + cargo are in PATH
export PATH="$HOME/.bun/bin:$HOME/.cargo/bin:$PATH"

# ── 1. Build Svelte static site ──
echo "[1/4] Building frontend..."
cd "$FRONTEND"
bun run build
echo "   Done: Svelte build"

# ── 2. Build Tauri release binary ──
echo "[2/4] Building Tauri binary (release)..."
cd "$FRONTEND"
bun run tauri build 2>&1 | tail -5
echo "   Done: Binary at src-tauri/target/release/lexicon-frontend"

# ── 3. Kill stale backend / frontend / shell service if running ──
kill $(lsof -ti :8000) 2>/dev/null || true
kill $(lsof -ti :8765) 2>/dev/null || true
pkill -x lexicon-frontend 2>/dev/null || true
sleep 0.5

# ── 4. Set up shell microservice venv if needed ──
if [ ! -d "$SHELL_SVC/.venv" ]; then
  echo "[3.5/5] Setting up shell microservice..."
  cd "$SHELL_SVC"
  uv venv .venv
  .venv/bin/pip install websockets
  echo "   Done: Shell service venv"
fi

# ── 5. Start shell microservice (PTY session manager on :8765) ──
echo "[3/5] Starting shell microservice on :8765..."
cd "$SHELL_SVC"
.venv/bin/python shell_server.py &
SHELL_PID=$!

# ── 6. Start backend (includes Spine ZeroMQ bus) ──
echo "[4/5] Starting backend + Spine on :8000..."
cd "$BACKEND"
.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload &
BACK_PID=$!

# ── 7. Start Tauri client ──
echo "[5/5] Starting Tauri client (hidden until toggled)..."
sleep 1  # let backend start first
"$FRONTEND/src-tauri/target/release/lexicon-frontend" &
TAURI_PID=$!

cleanup() {
  echo ""
  echo "Stopping Lexicon..."
  kill $TAURI_PID 2>/dev/null
  kill $BACK_PID 2>/dev/null
  kill $SHELL_PID 2>/dev/null
  wait $TAURI_PID 2>/dev/null
  wait $BACK_PID 2>/dev/null
  wait $SHELL_PID 2>/dev/null
  echo "Done"
}
trap cleanup EXIT INT TERM

sleep 1
echo ""
echo "=============================================="
echo "  Lexicon is running"
echo ""
echo "  Toggle:   ./lexicon-toggle"
echo "  Fallback: curl -X POST localhost:8000/toggle"
echo "  Backend:  http://localhost:8000"
echo "  Shell:    ws://localhost:8765"
echo "  Spine:    ZeroMQ SUB:5557 PUB:5556"
echo ""
echo "  Bind lexicon-toggle to Super+\` in your DE"
echo "  Ctrl+\` in Lexicon to toggle terminal"
echo "  Ctrl+C to stop everything"
echo "=============================================="
echo ""

wait
