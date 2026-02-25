# Lexicon Shell Microservice

**Layer 4** — PTY-based interactive shell session manager.

## Architecture

```
Frontend (Skin) ←WS→ Brain (FastAPI :8000) ←WS→ Shell Service (:8765)
```

The Shell Microservice provides **real pseudo-terminal (PTY) sessions** over WebSocket. Unlike the old approach (piping stdin/stdout of a subprocess), this gives us:

- **Real PTY**: programs think they're in a real terminal
- **Full color support**: ANSI 256-color and truecolor work out of the box
- **Interactive programs**: btop, vim, tmux, htop — all work
- **Shell detection**: auto-detects `$SHELL` (zsh, bash, fish, etc.)
- **Persistent sessions**: cd, env changes, aliases all persist
- **Terminal resize**: proper TIOCSWINSZ support
- **Signal handling**: Ctrl+C, Ctrl+D, Ctrl+Z work natively

## Protocol

### Client → Server

| Message | Description |
|---------|-------------|
| `{ "type": "spawn", "cols": 120, "rows": 30 }` | Start a new shell session |
| `{ "type": "input", "data": "ls -la\r" }` | Send keystrokes / data |
| `{ "type": "resize", "cols": 120, "rows": 40 }` | Resize the PTY |
| `{ "type": "signal", "sig": "INT" }` | Send a signal (INT, TSTP, QUIT, etc.) |
| `{ "type": "kill" }` | Terminate the session |

### Server → Client

| Message | Description |
|---------|-------------|
| `{ "type": "shell_info", "shell": "/bin/zsh", ... }` | Initial shell info |
| `{ "type": "spawned", "pid": 12345, "shell": "/bin/zsh" }` | Session started |
| `{ "type": "output", "data": "..." }` | Terminal output (may contain ANSI) |
| `{ "type": "exited", "exit_code": 0 }` | Session ended |
| `{ "type": "error", "message": "..." }` | Error message |

## Running

```bash
# Setup (first time)
uv venv .venv
uv pip install websockets --python .venv/bin/python

# Start
.venv/bin/python shell_server.py
```

The service listens on `ws://127.0.0.1:8765`.

## Frontend Integration

The frontend uses [xterm.js](https://xtermjs.org/) to render the terminal. The synapse bar detects shell commands (prefix `!` or known commands like `ls`, `cd`, `git`, etc.) and pipes them to the terminal. Press **Ctrl+`** to toggle the terminal panel.
