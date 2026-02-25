#!/usr/bin/env bash

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/lexicon-backend"
FRONTEND_DIR="$PROJECT_ROOT/lexicon-frontend"

echo "🧠 Starting Lexicon Backend..."
cd "$BACKEND_DIR"

# Kill any existing backend on port 8000
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

# Start backend in background
uv run python -m src.main &
BACKEND_PID=$!
echo "   Backend running (PID: $BACKEND_PID)"

# Wait for backend to be ready
echo "   Waiting for backend..."
for i in {1..30}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "   ✅ Backend ready"
        break
    fi
    sleep 0.5
done

echo ""
echo "🚀 Running Tauri Preview..."
cd "$FRONTEND_DIR"

# Check if binary exists
if [ ! -f "src-tauri/target/release/lexicon-frontend" ]; then
    echo "❌ Binary not found. Run 'bun run tauri build' first."
    kill $BACKEND_PID 2>/dev/null
    exit 1
fi

# Run the built binary
"$FRONTEND_DIR/src-tauri/target/release/lexicon-frontend" &
TAURI_PID=$!

# Cleanup on exit
trap "echo ''; echo 'Shutting down...'; kill $BACKEND_PID $TAURI_PID 2>/dev/null; exit" INT TERM EXIT

# Wait for user interrupt
wait