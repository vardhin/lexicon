#!/usr/bin/env bash
#
# lexicon-toggle — toggle the Lexicon overlay.
#
# Sends a message to the Spine (ZeroMQ) to toggle visibility.
# Falls back to HTTP POST if ZeroMQ isn't available.
#
# Usage:
#   ./lexicon-toggle        # via ZeroMQ (fast, <1ms)
#   ./lexicon-toggle --http # via curl fallback
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$SCRIPT_DIR/lexicon-backend"
SPINE_PORT=5557
HTTP_PORT=8000

# ── Try ZeroMQ first (preferred — fastest path) ──
if [ "$1" != "--http" ]; then
    # Use Python + pyzmq from the backend venv
    # PUSH/PULL pattern — no slow-joiner, guaranteed delivery
    if "$BACKEND/.venv/bin/python" -c "
import zmq
ctx = zmq.Context()
sock = ctx.socket(zmq.PUSH)
sock.connect('tcp://127.0.0.1:$SPINE_PORT')
sock.send_string('lexicon/toggle')
sock.close()
ctx.term()
" 2>/dev/null; then
        exit 0
    fi
fi

# ── Fallback: HTTP POST ──

