"""
Entry point for running the Lexicon Brain server.

Usage:
  uv run python -m src.run
  # or
  uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
"""

import uvicorn


def main():
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
