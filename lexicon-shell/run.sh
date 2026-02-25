#!/usr/bin/env bash
# Run the Lexicon Shell Microservice
cd "$(dirname "$0")"

# Create venv if needed
if [ ! -d .venv ]; then
    echo "🐚 Creating shell service venv..."
    uv venv .venv
    uv pip install -e .
fi

exec .venv/bin/python shell_server.py
