#!/usr/bin/env bash
#
# dev.sh — build everything + start backend, then use Super+` to open Lexicon.
#
# Usage:  ./dev.sh
# Stop:   Ctrl+C (kills backend)
#

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/lexicon-backend"
FRONTEND="$ROOT/lexicon-frontend"

# ensure bun + cargo are in PATH
export PATH="$HOME/.bun/bin:$HOME/.cargo/bin:$PATH"

# ── 1. Build Svelte static site ──
echo "📦 Building frontend..."
cd "$FRONTEND"
bun run build
echo "   ✔ Svelte build done"

# ── 2. Build Tauri release binary ──
echo "� Building Tauri binary (release)..."
cd "$FRONTEND"
bun run tauri build 2>&1 | tail -5
echo "   ✔ Binary at src-tauri/target/release/lexicon-frontend"

# ── 3. Kill stale backend / frontend if running ──
kill $(lsof -ti :8000) 2>/dev/null || true
pkill -x lexicon-frontend 2>/dev/null || true
sleep 0.5

# ── 4. Start backend ──
echo "🧠 Starting backend on :8000..."
cd "$BACKEND"
.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload &
BACK_PID=$!

cleanup() {
  echo ""
  echo "🛑 Stopping backend..."
  kill $BACK_PID 2>/dev/null
  wait $BACK_PID 2>/dev/null
  echo "✔ Done"
}
trap cleanup EXIT INT TERM

sleep 1
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Ready — press Super+\` to open Lexicon"
echo "  Backend running on http://localhost:8000"
echo "  Ctrl+C to stop"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

wait
