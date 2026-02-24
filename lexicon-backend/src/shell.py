"""
Persistent Shell — a long-running zsh session per WebSocket connection.

Instead of spawning a new process per command, we keep a single zsh
process alive.  Commands are written to stdin, and a unique sentinel
marker after each command lets us know when output is complete and
what the exit code was.

This means:
  - `cd` persists between commands
  - environment changes (`export`, `z`, `nvm use`, etc.) stick
  - we can kill a running command with SIGINT (Ctrl+C)

Interactive / TUI programs (btop, vim, htop, etc.) are detected and
rejected with a helpful message — they need a real terminal that a
WebSocket overlay can't provide.
"""

import asyncio
import os
import signal
import uuid

# Programs that require a real PTY / TUI — we can't render them.
_TUI_PROGRAMS = frozenset({
    "btop", "htop", "top", "vim", "nvim", "vi", "nano", "micro", "helix",
    "less", "more", "man", "fzf", "ranger", "nnn", "lf", "mc",
    "tmux", "screen", "ssh", "telnet", "nload", "iftop", "bmon",
    "watch", "dialog", "whiptail", "ncdu", "cfdisk", "nmtui",
})

# Unique sentinel we echo after every command to detect completion.
_SENTINEL = "__LEXICON_DONE__"


class PersistentShell:
    """A single zsh process that lives for the lifetime of a WS connection."""

    def __init__(self):
        self.proc = None
        self._current_shell_id = None
        self._lock = asyncio.Lock()
        self._cwd = os.environ.get("HOME", "/home/vardhin")

    async def start(self):
        """Spawn the zsh process."""
        env = {**os.environ, "TERM": "dumb"}
        self.proc = await asyncio.create_subprocess_exec(
            "/usr/bin/zsh", "--login", "--no-rcs",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=self._cwd,
            # Create a new process group so we can signal just the child tree
            preexec_fn=os.setsid,
        )
        # Source the user's profile for PATH, aliases, etc. but skip
        # interactive-only stuff by using --no-rcs above and sourcing manually.
        # We source .zshenv (always) and .zprofile (login) but NOT .zshrc
        # (which has fastfetch and other interactive junk).
        init_cmds = [
            '[ -f "$HOME/.zshenv" ] && source "$HOME/.zshenv" 2>/dev/null',
            '[ -f "$HOME/.zprofile" ] && source "$HOME/.zprofile" 2>/dev/null',
            # Source just the non-interactive parts of .zshrc:
            # aliases, PATH additions, plugin inits — but skip anything
            # that produces output. We use a trick: set a flag and let
            # .zshrc check it to skip greetings.
            'export LEXICON_SHELL=1',
            # Source .zshrc but suppress its output
            '[ -f "$HOME/.zshrc" ] && source "$HOME/.zshrc" &>/dev/null',
            f'echo "{_SENTINEL} 0"',
        ]
        full_init = "\n".join(init_cmds) + "\n"
        self.proc.stdin.write(full_init.encode())
        await self.proc.stdin.drain()

        # Wait for the init sentinel
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace")
            if _SENTINEL in text:
                break

    async def run_command(self, ws, shell_id: str, cmd: str, memory):
        """Execute a command in the persistent shell, streaming output."""
        if not self.proc or self.proc.returncode is not None:
            await self.start()

        # Check for TUI programs
        first_word = cmd.strip().split()[0] if cmd.strip() else ""
        # Handle pipes/sudo: check last piped command too
        pipe_parts = cmd.split("|")
        all_words = [p.strip().split()[0] for p in pipe_parts if p.strip()]
        # Also handle sudo prefix
        check_words = []
        for w in all_words:
            check_words.append(w)
        for part in pipe_parts:
            tokens = part.strip().split()
            if len(tokens) >= 2 and tokens[0] == "sudo":
                check_words.append(tokens[1])

        for w in check_words:
            if w in _TUI_PROGRAMS:
                await ws.send_json({
                    "type": "SHELL_OUTPUT",
                    "shell_id": shell_id,
                    "text": f"⚠ '{w}' is a TUI/interactive program that needs a real terminal.\n"
                            f"  Run it in Kitty/Alacritty instead, or use a non-interactive alternative.\n",
                })
                await ws.send_json({
                    "type": "SHELL_DONE",
                    "shell_id": shell_id,
                    "exit_code": 1,
                })
                return

        async with self._lock:
            self._current_shell_id = shell_id
            collected = []

            try:
                # Write the command followed by our sentinel
                # The sentinel echoes the exit code of the previous command
                script = f'{cmd}\necho "{_SENTINEL} $?"\n'
                self.proc.stdin.write(script.encode())
                await self.proc.stdin.drain()

                # Read output until we see the sentinel
                while True:
                    try:
                        line = await asyncio.wait_for(
                            self.proc.stdout.readline(), timeout=60
                        )
                    except asyncio.TimeoutError:
                        await ws.send_json({
                            "type": "SHELL_OUTPUT",
                            "shell_id": shell_id,
                            "text": "⚠ Command timed out after 60s\n",
                        })
                        # Kill the current command
                        await self.kill_current()
                        await ws.send_json({
                            "type": "SHELL_DONE",
                            "shell_id": shell_id,
                            "exit_code": 124,
                        })
                        await memory.save_shell_session(
                            shell_id, cmd, "".join(collected) + "\n⚠ Timed out\n", 124
                        )
                        return

                    if not line:
                        # Process died
                        await ws.send_json({
                            "type": "SHELL_DONE",
                            "shell_id": shell_id,
                            "exit_code": -1,
                        })
                        await memory.save_shell_session(
                            shell_id, cmd, "".join(collected), -1
                        )
                        return

                    text = line.decode("utf-8", errors="replace")

                    # Check for sentinel
                    if _SENTINEL in text:
                        # Parse exit code from sentinel line
                        try:
                            exit_code = int(text.strip().split()[-1])
                        except (ValueError, IndexError):
                            exit_code = 0

                        await ws.send_json({
                            "type": "SHELL_DONE",
                            "shell_id": shell_id,
                            "exit_code": exit_code,
                        })

                        # Persist
                        full_output = "".join(collected)
                        if len(full_output) > 65536:
                            full_output = full_output[:65536] + "\n… (truncated)\n"
                        await memory.save_shell_session(
                            shell_id, cmd, full_output, exit_code
                        )
                        return

                    collected.append(text)
                    await ws.send_json({
                        "type": "SHELL_OUTPUT",
                        "shell_id": shell_id,
                        "text": text,
                    })

            except Exception as e:
                await ws.send_json({
                    "type": "SHELL_OUTPUT",
                    "shell_id": shell_id,
                    "text": f"Error: {e}\n",
                })
                await ws.send_json({
                    "type": "SHELL_DONE",
                    "shell_id": shell_id,
                    "exit_code": -1,
                })
            finally:
                self._current_shell_id = None

    async def kill_current(self):
        """Send SIGINT to the shell's process group (like Ctrl+C)."""
        if self.proc and self.proc.returncode is None:
            try:
                # Send SIGINT to the entire process group
                os.killpg(os.getpgid(self.proc.pid), signal.SIGINT)
            except (ProcessLookupError, PermissionError):
                pass

    async def get_cwd(self):
        """Ask the shell for its current working directory."""
        if not self.proc or self.proc.returncode is not None:
            return self._cwd
        # We can't easily query this without running a command,
        # so we return the initial cwd. The actual cwd changes
        # are visible via `pwd` command.
        return self._cwd

    async def close(self):
        """Shut down the shell process."""
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.stdin.write(b"exit\n")
                await self.proc.stdin.drain()
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    self.proc.kill()
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
