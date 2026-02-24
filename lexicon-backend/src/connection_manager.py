from fastapi import WebSocket


class ConnectionManager:
    """Manages active WebSocket connections (Skin Connections)."""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket, connection_id: str):
        await ws.accept()
        self._connections[connection_id] = ws
        print(f"🔗 Client {connection_id} connected (total: {self.active_count})")

    def disconnect(self, connection_id: str):
        self._connections.pop(connection_id, None)
        print(f"🔌 Client {connection_id} removed (total: {self.active_count})")

    async def disconnect_all(self):
        for cid, ws in list(self._connections.items()):
            try:
                await ws.close()
            except Exception:
                pass
        self._connections.clear()

    async def broadcast(self, message: dict):
        """Send a message to all connected clients."""
        dead = []
        for cid, ws in self._connections.items():
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self._connections.pop(cid, None)

    async def send_to(self, connection_id: str, message: dict):
        ws = self._connections.get(connection_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                self._connections.pop(connection_id, None)

    @property
    def active_count(self) -> int:
        return len(self._connections)
