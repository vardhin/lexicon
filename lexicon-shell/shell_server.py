"""
Lexicon Shell Microservice — PTY-based interactive shell manager.

This microservice provides real pseudo-terminal (PTY) shell sessions
over WebSocket. It is a Layer 4 microservice in the Lexicon architecture.

Architecture:
  Frontend (Skin) ←WS→ Brain (FastAPI :8000) ←WS→ Shell Service (:8765)

Key features:
  - Auto-detects the user's default shell ($SHELL / /etc/passwd)
  - Spawns a real PTY so programs think they're in a real terminal
  - Full color support, interactive programs (btop, vim, etc.)
  - cd/env changes persist across commands (real shell session)
  - Supports terminal resize (TIOCSWINSZ)
  - Ctrl+C / Ctrl+D / Ctrl+Z work natively
  - Streams raw bytes bidirectionally

Protocol (JSON over WebSocket):
  Client → Server:
    { "type": "spawn",  "cols": 120, "rows": 30 }     — start a new session
    { "type": "input",  "data": "ls -la\r" }           — send keystrokes / data
    { "type": "resize", "cols": 120, "rows": 40 }      — resize the PTY
    { "type": "kill" }                                  — send SIGHUP + terminate
    { "type": "signal", "sig": "INT" }                  — send a signal (INT, TSTP, etc.)

  Server → Client:
    { "type": "output",   "data": "..." }               — terminal output (may contain ANSI)
    { "type": "spawned",  "pid": 12345, "shell": "/bin/zsh" }
    { "type": "exited",   "exit_code": 0 }
    { "type": "error",    "message": "..." }
    { "type": "shell_info", "shell": "/bin/zsh", "user": "vardhin", "home": "/home/vardhin", "cwd": "/home/vardhin" }
"""

import asyncio
import fcntl
import json
import os
import pty
import pwd
import signal
import struct
import sys
import termios
import websockets
import websockets.asyncio.server


# ── Shell detection ──────────────────────────────────────────────

def detect_shell() -> str:
    """Detect the user's default shell. Platform-agnostic."""
    # 1. $SHELL env var (most reliable on Unix)
    shell = os.environ.get("SHELL")
    if shell and os.path.isfile(shell):
        return shell

    # 2. From /etc/passwd
    try:
        pw = pwd.getpwuid(os.getuid())
        if pw.pw_shell and os.path.isfile(pw.pw_shell):
            return pw.pw_shell
    except (KeyError, ImportError):
        pass

    # 3. Fallback chain
    for candidate in ["/bin/zsh", "/bin/bash", "/bin/sh"]:
        if os.path.isfile(candidate):
            return candidate

    return "/bin/sh"


def get_user_info() -> dict:
    """Gather user context for the shell session."""
    try:
        pw = pwd.getpwuid(os.getuid())
        username = pw.pw_name
        home = pw.pw_dir
    except (KeyError, ImportError):
        username = os.environ.get("USER", "user")
        home = os.environ.get("HOME", "/tmp")

    return {
        "user": username,
        "home": home,
        "shell": detect_shell(),
        "cwd": home,
    }


# ── PTY Session ──────────────────────────────────────────────────

class PTYSession:
    """Manages a single PTY shell session."""

    def __init__(self, shell: str, cols: int = 120, rows: int = 30):
        self.shell = shell
        self.cols = cols
        self.rows = rows
        self.master_fd: int | None = None
        self.child_pid: int | None = None
        self._alive = False

    def spawn(self) -> int:
        """Fork a child process with a PTY. Returns child PID."""
        user_info = get_user_info()
        env = {
            **os.environ,
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "SHELL": self.shell,
            "HOME": user_info["home"],
            "USER": user_info["user"],
            "LOGNAME": user_info["user"],
            "LEXICON_SHELL": "1",  # Let .zshrc/.bashrc know we're in Lexicon
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", ""),
        }
        # Remove empty values
        env = {k: v for k, v in env.items() if v}

        # pty.fork() handles the master/slave dance correctly:
        #   - In parent: returns (child_pid, master_fd)
        #   - In child:  returns (0, <irrelevant>), with stdio wired to slave
        self.child_pid, self.master_fd = pty.fork()

        if self.child_pid == 0:
            # ── Child process ──
            # stdio is already connected to the slave PTY by pty.fork()

            # Set initial terminal size
            winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
            fcntl.ioctl(0, termios.TIOCSWINSZ, winsize)

            # cd to home
            os.chdir(user_info["home"])

            # Exec the shell as a login shell
            shell_name = os.path.basename(self.shell)
            os.execvpe(self.shell, [f"-{shell_name}"], env)
            # execvpe never returns; if it does, exit
            os._exit(1)

        else:
            # ── Parent process ──
            # Set initial window size on master
            winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
            try:
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except OSError:
                pass

            # Make master_fd non-blocking
            flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            self._alive = True
            return self.child_pid

    def resize(self, cols: int, rows: int):
        """Resize the PTY window."""
        self.cols = cols
        self.rows = rows
        if self.master_fd is not None:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            try:
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except OSError:
                pass
            # Notify the child of the size change
            if self.child_pid:
                try:
                    os.kill(self.child_pid, signal.SIGWINCH)
                except (ProcessLookupError, PermissionError):
                    pass

    def write(self, data: bytes):
        """Write data to the PTY master (i.e., send to the shell's stdin)."""
        if self.master_fd is not None:
            try:
                os.write(self.master_fd, data)
            except OSError:
                pass

    def read(self, size: int = 65536) -> bytes | None:
        """Non-blocking read from the PTY master (shell's stdout+stderr)."""
        if self.master_fd is None:
            return None
        try:
            return os.read(self.master_fd, size)
        except (OSError, BlockingIOError):
            return None

    def send_signal(self, sig: signal.Signals):
        """Send a signal to the child process."""
        if self.child_pid:
            try:
                os.kill(self.child_pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

    def is_alive(self) -> bool:
        """Check if the child process is still running."""
        if not self.child_pid:
            return False
        try:
            pid, status = os.waitpid(self.child_pid, os.WNOHANG)
            if pid == 0:
                return True
            self._alive = False
            return False
        except ChildProcessError:
            self._alive = False
            return False

    def get_exit_code(self) -> int:
        """Get exit code of the child (call after is_alive() returns False)."""
        if not self.child_pid:
            return -1
        try:
            _, status = os.waitpid(self.child_pid, os.WNOHANG)
            if os.WIFEXITED(status):
                return os.WEXITSTATUS(status)
            if os.WIFSIGNALED(status):
                return 128 + os.WTERMSIG(status)
        except ChildProcessError:
            pass
        return -1

    def kill(self):
        """Kill the shell session."""
        self._alive = False
        if self.child_pid:
            try:
                os.kill(self.child_pid, signal.SIGHUP)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                os.kill(self.child_pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                os.waitpid(self.child_pid, os.WNOHANG)
            except ChildProcessError:
                pass
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None
        self.child_pid = None


# ── WebSocket Handler ────────────────────────────────────────────

async def handle_client(ws):
    """Handle a single WebSocket client connection."""
    session: PTYSession | None = None
    reader_task: asyncio.Task | None = None
    user_info = get_user_info()

    # Send shell info immediately
    await ws.send(json.dumps({
        "type": "shell_info",
        "shell": user_info["shell"],
        "user": user_info["user"],
        "home": user_info["home"],
        "cwd": user_info["home"],
    }))

    async def pty_reader():
        """Background task: read from PTY and send to WebSocket."""
        loop = asyncio.get_event_loop()
        fd = session.master_fd

        try:
            while session and session.is_alive():
                # Wait for data to be available on the PTY fd
                readable = asyncio.Event()
                loop.add_reader(fd, readable.set)
                try:
                    await asyncio.wait_for(readable.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    # No data yet — check if process is still alive
                    continue
                finally:
                    loop.remove_reader(fd)

                # Read all available data
                try:
                    data = os.read(fd, 65536)
                    if data:
                        await ws.send(json.dumps({
                            "type": "output",
                            "data": data.decode("utf-8", errors="replace"),
                        }))
                    else:
                        # EOF — process likely exited
                        break
                except OSError:
                    break

            # Process exited
            exit_code = session.get_exit_code() if session else -1
            await ws.send(json.dumps({
                "type": "exited",
                "exit_code": exit_code,
            }))
        except websockets.exceptions.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"  pty_reader error: {e}")

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            if msg_type == "spawn":
                # Kill existing session if any
                if session:
                    session.kill()
                    if reader_task:
                        reader_task.cancel()
                        try:
                            await reader_task
                        except asyncio.CancelledError:
                            pass

                cols = msg.get("cols", 120)
                rows = msg.get("rows", 30)
                shell = user_info["shell"]

                session = PTYSession(shell, cols, rows)
                pid = session.spawn()

                await ws.send(json.dumps({
                    "type": "spawned",
                    "pid": pid,
                    "shell": shell,
                }))

                # Start reading PTY output
                reader_task = asyncio.create_task(pty_reader())

            elif msg_type == "input":
                if session:
                    data = msg.get("data", "")
                    session.write(data.encode("utf-8"))

            elif msg_type == "resize":
                if session:
                    cols = msg.get("cols", 120)
                    rows = msg.get("rows", 30)
                    session.resize(cols, rows)

            elif msg_type == "signal":
                if session:
                    sig_name = msg.get("sig", "INT").upper()
                    sig_map = {
                        "INT": signal.SIGINT,
                        "TSTP": signal.SIGTSTP,
                        "QUIT": signal.SIGQUIT,
                        "TERM": signal.SIGTERM,
                        "KILL": signal.SIGKILL,
                        "HUP": signal.SIGHUP,
                    }
                    sig = sig_map.get(sig_name, signal.SIGINT)
                    session.send_signal(sig)

            elif msg_type == "kill":
                if session:
                    session.kill()
                    session = None
                    await ws.send(json.dumps({
                        "type": "exited",
                        "exit_code": -1,
                    }))

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        # Cleanup
        if reader_task:
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass
        if session:
            session.kill()
        print(f"  Client disconnected")


# ── Main ─────────────────────────────────────────────────────────

SHELL_WS_HOST = "127.0.0.1"
SHELL_WS_PORT = 8765


async def serve():
    user_info = get_user_info()
    print(f"🐚 Lexicon Shell Microservice starting...")
    print(f"   Shell:  {user_info['shell']}")
    print(f"   User:   {user_info['user']}")
    print(f"   Home:   {user_info['home']}")
    print(f"   Listen: ws://{SHELL_WS_HOST}:{SHELL_WS_PORT}")

    async with websockets.asyncio.server.serve(
        handle_client,
        SHELL_WS_HOST,
        SHELL_WS_PORT,
        max_size=2**20,  # 1 MB max message size
    ):
        print(f"🐚 Shell service ready on ws://{SHELL_WS_HOST}:{SHELL_WS_PORT}")
        await asyncio.Future()  # Run forever


def main():
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        print("\n🐚 Shell service stopped")


if __name__ == "__main__":
    main()
