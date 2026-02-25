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

# ── 3. Kill stale backend / frontend if running ──
kill $(lsof -ti :8000) 2>/dev/null || true
pkill -x lexicon-frontend 2>/dev/null || true
sleep 0.5

# ── 4. Start backend (includes Spine ZeroMQ bus) ──
echo "[3/4] Starting backend + Spine on :8000..."
cd "$BACKEND"
.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload &
BACK_PID=$!

# ── 5. Start Tauri client ──
echo "[4/4] Starting Tauri client (hidden until toggled)..."
sleep 1  # let backend start first
"$FRONTEND/src-tauri/target/release/lexicon-frontend" &
TAURI_PID=$!

cleanup() {
  echo ""
  echo "Stopping Lexicon..."
  kill $TAURI_PID 2>/dev/null
  kill $BACK_PID 2>/dev/null
  wait $TAURI_PID 2>/dev/null
  wait $BACK_PID 2>/dev/null
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
echo "  Spine:    ZeroMQ SUB:5557 PUB:5556"
echo ""
echo "  Bind lexicon-toggle to Super+\` in your DE"
echo "  Ctrl+C to stop everything"
echo "=============================================="
echo ""

wait
