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


def _sanitize_for_json(obj):
    """Recursively convert SurrealDB types (RecordID, etc.) to JSON-safe types."""
    if obj is None:
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    # Convert RecordID and any other non-serializable types to string
    type_name = type(obj).__name__
    if type_name == 'RecordID':
        return str(obj)
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    # Check if it's a basic JSON type
    if isinstance(obj, (str, int, float, bool)):
        return obj
    # Fallback: stringify unknown types
    return str(obj)

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
            return [r["name"] for r in _sanitize_for_json(result)]
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
            return _sanitize_for_json(result[0]["widgets"])
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
        return _sanitize_for_json(result) if result else []

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
        # Sanitize and reverse to chronological order
        sanitized = _sanitize_for_json(result)
        return list(reversed(sanitized))

    # ── Generic Organ Management ──────────────────────────

    async def list_organs(self):
        """Get all registered organs."""
        if not self.db:
            return []
        result = await self.db.query(
            "SELECT organ_id, url, name, created_at FROM organ ORDER BY created_at ASC"
        )
        if not result:
            return []
        return _sanitize_for_json(result)

    async def get_organ(self, organ_id: str):
        """Get a single organ by ID."""
        if not self.db:
            return None
        result = await self.db.query(
            "SELECT * FROM organ WHERE organ_id = $oid",
            {"oid": organ_id},
        )
        if result and len(result) > 0:
            return _sanitize_for_json(result[0])
        return None

    async def create_organ(self, organ_id: str, url: str, name: str = ""):
        """Register a new organ."""
        if not self.db:
            return
        # Check if already exists
        existing = await self.db.query(
            "SELECT * FROM organ WHERE organ_id = $oid",
            {"oid": organ_id},
        )
        if existing and len(existing) > 0:
            # Update URL and name
            await self.db.query(
                "UPDATE organ SET url = $url, name = $name WHERE organ_id = $oid",
                {"oid": organ_id, "url": url, "name": name},
            )
            return
        await self.db.query(
            "CREATE organ SET organ_id = $oid, url = $url, name = $name, created_at = time::now()",
            {"oid": organ_id, "url": url, "name": name},
        )

    async def delete_organ(self, organ_id: str):
        """Delete an organ and all its data."""
        if not self.db:
            return
        await self.db.query("DELETE organ WHERE organ_id = $oid", {"oid": organ_id})
        await self.db.query("DELETE scrape_pattern WHERE organ_id = $oid", {"oid": organ_id})
        await self.db.query("DELETE scraped_data WHERE organ_id = $oid", {"oid": organ_id})

    # ── Scrape Patterns ───────────────────────────────────

    async def save_scrape_pattern(self, organ_id: str, class_name: str,
                                   outer_html: str, fingerprint: dict):
        """Save (upsert) a scrape pattern for an organ."""
        if not self.db:
            return
        await self.db.query(
            "DELETE scrape_pattern WHERE organ_id = $oid AND class_name = $cname",
            {"oid": organ_id, "cname": class_name},
        )
        await self.db.query(
            "CREATE scrape_pattern SET organ_id = $oid, class_name = $cname, "
            "outer_html = $ohtml, fingerprint = $fp, updated_at = time::now()",
            {"oid": organ_id, "cname": class_name, "ohtml": outer_html, "fp": fingerprint},
        )

    async def get_scrape_patterns(self, organ_id: str) -> list:
        """Get all scrape patterns for an organ."""
        if not self.db:
            return []
        result = await self.db.query(
            "SELECT class_name, outer_html, fingerprint, updated_at "
            "FROM scrape_pattern WHERE organ_id = $oid ORDER BY class_name ASC",
            {"oid": organ_id},
        )
        if not result:
            return []
        return _sanitize_for_json(result)

    async def delete_scrape_pattern(self, organ_id: str, class_name: str):
        """Delete a scrape pattern and its stored data."""
        if not self.db:
            return
        await self.db.query(
            "DELETE scrape_pattern WHERE organ_id = $oid AND class_name = $cname",
            {"oid": organ_id, "cname": class_name},
        )
        await self.db.query(
            "DELETE scraped_data WHERE organ_id = $oid AND class_name = $cname",
            {"oid": organ_id, "cname": class_name},
        )

    # ── Scraped Data ──────────────────────────────────────

    async def store_scraped_data(self, organ_id: str, class_name: str, values: list):
        """Store scraped data (replaces previous data for this class)."""
        if not self.db:
            return
        await self.db.query(
            "DELETE scraped_data WHERE organ_id = $oid AND class_name = $cname",
            {"oid": organ_id, "cname": class_name},
        )
        await self.db.query(
            "CREATE scraped_data SET organ_id = $oid, class_name = $cname, "
            "values = $vals, count = $count, scraped_at = time::now()",
            {"oid": organ_id, "cname": class_name, "vals": values, "count": len(values)},
        )

    async def get_scraped_data(self, organ_id: str, class_name: str = None) -> list:
        """Get scraped data for an organ, optionally filtered by class_name."""
        if not self.db:
            return []
        if class_name:
            result = await self.db.query(
                "SELECT class_name, values, count, scraped_at "
                "FROM scraped_data WHERE organ_id = $oid AND class_name = $cname",
                {"oid": organ_id, "cname": class_name},
            )
        else:
            result = await self.db.query(
                "SELECT class_name, values, count, scraped_at "
                "FROM scraped_data WHERE organ_id = $oid ORDER BY class_name ASC",
                {"oid": organ_id},
            )
        if not result:
            return []
        return _sanitize_for_json(result)
