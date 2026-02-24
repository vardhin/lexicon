"""
Memory — SurrealDB embedded storage for Lexicon.

Stores:
  - UI state (which widgets were open when frontend closed)
  - Command history
  - Shell sessions (cmd + output + exit code)
  - Workspaces (named collections of state)

Uses surrealkv:// (file-backed, no server needed).
"""

import os
from surrealdb import AsyncSurreal

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "infra", "data")
DB_URL = f"surrealkv://{os.path.normpath(DATA_DIR)}"

DEFAULT_WORKSPACE = "default"


class Memory:
    def __init__(self):
        self.db = None
        self.workspace = DEFAULT_WORKSPACE

    async def connect(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.db = AsyncSurreal(DB_URL)
        await self.db.connect()
        await self.db.use("lexicon", "lexicon")
        # Ensure default workspace exists
        await self._ensure_workspace(DEFAULT_WORKSPACE)
        print(f"💾 Memory connected ({DB_URL})")

    async def close(self):
        if self.db:
            await self.db.close()
            self.db = None
            print("💾 Memory closed")

    # ── Workspaces ────────────────────────────────────────

    async def _ensure_workspace(self, name):
        """Create workspace record if it doesn't exist."""
        if not self.db:
            return
        result = await self.db.query(
            "SELECT * FROM workspace WHERE name = $name",
            {"name": name},
        )
        if not result:
            await self.db.query(
                "CREATE workspace SET name = $name, created_at = time::now()",
                {"name": name},
            )

    async def list_workspaces(self):
        """Return all workspace names."""
        if not self.db:
            return [DEFAULT_WORKSPACE]
        result = await self.db.query(
            "SELECT name, created_at FROM workspace ORDER BY created_at ASC"
        )
        if result:
            return [r["name"] for r in result]
        return [DEFAULT_WORKSPACE]

    async def create_workspace(self, name):
        """Create a new workspace and switch to it."""
        if not self.db:
            return
        await self._ensure_workspace(name)
        self.workspace = name

    async def switch_workspace(self, name):
        """Switch to an existing workspace."""
        self.workspace = name

    async def delete_workspace(self, name):
        """Delete a workspace and all its data. Can't delete 'default'."""
        if not self.db or name == DEFAULT_WORKSPACE:
            return
        ws = name
        await self.db.query(
            "DELETE workspace WHERE name = $ws", {"ws": ws}
        )
        await self.db.query(
            "DELETE state WHERE workspace = $ws", {"ws": ws}
        )
        await self.db.query(
            "DELETE shell_session WHERE workspace = $ws", {"ws": ws}
        )
        await self.db.query(
            "DELETE history WHERE workspace = $ws", {"ws": ws}
        )
        if self.workspace == name:
            self.workspace = DEFAULT_WORKSPACE

    async def get_current_workspace(self):
        return self.workspace

    # ── UI State ──────────────────────────────────────────

    async def save_state(self, widgets):
        """Save the current widget list for the active workspace."""
        if not self.db:
            return
        ws = self.workspace
        await self.db.query(
            "DELETE state WHERE workspace = $ws",
            {"ws": ws},
        )
        await self.db.query(
            "CREATE state SET workspace = $ws, widgets = $widgets, saved_at = time::now()",
            {"ws": ws, "widgets": widgets},
        )

    async def load_state(self):
        """Load the last saved widget list for the active workspace."""
        if not self.db:
            return []
        ws = self.workspace
        result = await self.db.query(
            "SELECT widgets FROM state WHERE workspace = $ws LIMIT 1",
            {"ws": ws},
        )
        if result and len(result) > 0 and "widgets" in result[0]:
            return result[0]["widgets"]
        return []

    async def clear_state(self):
        """Clear all widgets and shell sessions for the active workspace."""
        if not self.db:
            return
        ws = self.workspace
        await self.db.query("DELETE state WHERE workspace = $ws", {"ws": ws})
        await self.db.query("DELETE shell_session WHERE workspace = $ws", {"ws": ws})

    # ── Command History ───────────────────────────────────

    async def log_command(self, text):
        """Append a command to history."""
        if not self.db:
            return
        ws = self.workspace
        await self.db.query(
            "CREATE history SET text = $text, workspace = $ws, ts = time::now()",
            {"text": text, "ws": ws},
        )

    async def get_history(self, limit=50):
        """Get recent command history."""
        if not self.db:
            return []
        ws = self.workspace
        result = await self.db.query(
            "SELECT text, ts FROM history WHERE workspace = $ws ORDER BY ts DESC LIMIT $limit",
            {"ws": ws, "limit": limit},
        )
        return result if result else []

    # ── Shell Sessions ────────────────────────────────────

    async def save_shell_session(self, shell_id, cmd, output, exit_code):
        """Store a completed shell session."""
        if not self.db:
            return
        ws = self.workspace
        await self.db.query(
            "CREATE shell_session SET "
            "shell_id = $shell_id, cmd = $cmd, output = $output, "
            "exit_code = $exit_code, workspace = $ws, ts = time::now()",
            {
                "shell_id": shell_id,
                "cmd": cmd,
                "output": output,
                "exit_code": exit_code,
                "ws": ws,
            },
        )

    async def get_shell_sessions(self, limit=30):
        """Get recent shell sessions for restore."""
        if not self.db:
            return []
        ws = self.workspace
        result = await self.db.query(
            "SELECT shell_id, cmd, output, exit_code, ts "
            "FROM shell_session WHERE workspace = $ws ORDER BY ts DESC LIMIT $limit",
            {"ws": ws, "limit": limit},
        )
        if not result:
            return []
        # Convert datetime ts to ISO strings for JSON serialization
        sessions = []
        for row in reversed(result):
            entry = dict(row)
            ts = entry.get("ts")
            if hasattr(ts, "isoformat"):
                entry["ts"] = ts.isoformat()
            else:
                entry["ts"] = str(ts) if ts else None
            sessions.append(entry)
        return sessions
