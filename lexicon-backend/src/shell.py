"""
Shell Manager — manages multiple PTY sessions via the Shell Microservice.

Each session gets its own WebSocket connection to the Shell Microservice
(ws://127.0.0.1:8765), providing independent PTY sessions.

The Brain routes messages between the frontend and sessions by session_id:

  Frontend:  { type: "shell_spawn",  session_id: "s-abc123", cols: 120, rows: 30 }
  Frontend:  { type: "shell_input",  session_id: "s-abc123", data: "ls\r" }
  Backend ->: { type: "SHELL_OUTPUT", session_id: "s-abc123", data: "..." }

Multiple terminal widgets on the canvas each correspond to one session.
"""

import asyncio
import json

import websockets.asyncio.client

SHELL_SERVICE_URL = "ws://127.0.0.1:8765"


class _Session:
    """A single PTY session connected to the Shell Microservice."""

    def __init__(self, session_id: str, frontend_ws):
        self.session_id = session_id
        self._shell_ws = None
        self._reader_task: asyncio.Task | None = None
        self._frontend_ws = frontend_ws
        self._connected = False
        self._shell_info: dict | None = None

    async def connect(self, cols: int = 120, rows: int = 30):
        """Connect to the Shell Microservice and spawn a PTY."""
        try:
            self._shell_ws = await websockets.asyncio.client.connect(
                SHELL_SERVICE_URL,
                max_size=2**20,
            )
            self._connected = True

            # Read the initial shell_info message
            raw = await asyncio.wait_for(self._shell_ws.recv(), timeout=5)
            msg = json.loads(raw)
            if msg.get("type") == "shell_info":
                self._shell_info = msg

            # Request a shell session with the desired size
            await self._shell_ws.send(json.dumps({
                "type": "spawn",
                "cols": cols,
                "rows": rows,
            }))

            # Wait for spawned confirmation
            raw = await asyncio.wait_for(self._shell_ws.recv(), timeout=5)
            spawn_msg = json.loads(raw)

            # Notify the frontend
            await self._frontend_ws.send_json({
                "type": "SHELL_SPAWNED",
                "session_id": self.session_id,
                "shell": self._shell_info.get("shell", "unknown") if self._shell_info else "unknown",
                "pid": spawn_msg.get("pid", 0),
                "user": self._shell_info.get("user", "") if self._shell_info else "",
                "home": self._shell_info.get("home", "") if self._shell_info else "",
            })

            # Start the reader loop
            self._reader_task = asyncio.create_task(self._relay_output())

        except Exception as e:
            self._connected = False
            await self._frontend_ws.send_json({
                "type": "SHELL_ERROR",
                "session_id": self.session_id,
                "message": f"Failed to connect to shell service: {e}",
            })

    async def _relay_output(self):
        """Read from Shell Microservice and forward to Frontend with session_id."""
        try:
            async for raw in self._shell_ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if msg["type"] == "output":
                    await self._frontend_ws.send_json({
                        "type": "SHELL_OUTPUT",
                        "session_id": self.session_id,
                        "data": msg["data"],
                    })
                elif msg["type"] == "exited":
                    await self._frontend_ws.send_json({
                        "type": "SHELL_EXITED",
                        "session_id": self.session_id,
                        "exit_code": msg.get("exit_code", -1),
                    })
                    self._connected = False
                    break
        except Exception:
            self._connected = False
            try:
                await self._frontend_ws.send_json({
                    "type": "SHELL_EXITED",
                    "session_id": self.session_id,
                    "exit_code": -1,
                })
            except Exception:
                pass

    async def send_input(self, data: str):
        if self._shell_ws and self._connected:
            try:
                await self._shell_ws.send(json.dumps({"type": "input", "data": data}))
            except Exception:
                pass

    async def resize(self, cols: int, rows: int):
        if self._shell_ws and self._connected:
            try:
                await self._shell_ws.send(json.dumps({
                    "type": "resize", "cols": cols, "rows": rows,
                }))
            except Exception:
                pass

    async def send_signal(self, sig: str = "INT"):
        if self._shell_ws and self._connected:
            try:
                await self._shell_ws.send(json.dumps({"type": "signal", "sig": sig}))
            except Exception:
                pass

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def close(self):
        self._connected = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._shell_ws:
            try:
                await self._shell_ws.send(json.dumps({"type": "kill"}))
            except Exception:
                pass
            try:
                await self._shell_ws.close()
            except Exception:
                pass
            self._shell_ws = None


class ShellManager:
    """Manages multiple named PTY sessions for a single frontend connection."""

    def __init__(self):
        self._sessions: dict[str, _Session] = {}

    async def spawn(self, session_id: str, frontend_ws, cols: int = 120, rows: int = 30):
        """Spawn a new session or reconnect an existing one."""
        # Close existing session with same id if it exists
        if session_id in self._sessions:
            await self._sessions[session_id].close()

        session = _Session(session_id, frontend_ws)
        self._sessions[session_id] = session
        await session.connect(cols, rows)

    async def send_input(self, session_id: str, data: str):
        session = self._sessions.get(session_id)
        if session and session.is_connected:
            await session.send_input(data)

    async def resize(self, session_id: str, cols: int, rows: int):
        session = self._sessions.get(session_id)
        if session and session.is_connected:
            await session.resize(cols, rows)

    async def send_signal(self, session_id: str, sig: str = "INT"):
        session = self._sessions.get(session_id)
        if session and session.is_connected:
            await session.send_signal(sig)

    async def kill(self, session_id: str):
        session = self._sessions.pop(session_id, None)
        if session:
            await session.close()

    def is_connected(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        return session.is_connected if session else False

    async def close_all(self):
        for sid in list(self._sessions.keys()):
            await self.kill(sid)
