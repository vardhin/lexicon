"""
Memory — SurrealDB embedded storage for Lexicon.

Stores:
  - UI state (which widgets were open when frontend closed)
  - Command history
  - Future: context graph, user preferences, etc.

Uses surrealkv:// (file-backed, no server needed).
"""

import os
from surrealdb import AsyncSurreal

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "infra", "data")
DB_URL = f"surrealkv://{os.path.normpath(DATA_DIR)}"


class Memory:
    def __init__(self):
        self.db = None

    async def connect(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.db = AsyncSurreal(DB_URL)
        await self.db.connect()
        await self.db.use("lexicon", "lexicon")
        print(f"💾 Memory connected ({DB_URL})")

    async def close(self):
        if self.db:
            await self.db.close()
            self.db = None
            print("💾 Memory closed")

    # ── UI State ──────────────────────────────────────────

    async def save_state(self, widgets):
        """Save the current widget list so it can be restored on next launch."""
        if not self.db:
            return
        # Upsert a single state record
        await self.db.query(
            "DELETE state; CREATE state:current SET widgets = $widgets, saved_at = time::now()",
            {"widgets": widgets},
        )

    async def load_state(self):
        """Load the last saved widget list. Returns [] if none."""
        if not self.db:
            return []
        result = await self.db.query("SELECT widgets FROM state:current")
        if result and len(result) > 0 and "widgets" in result[0]:
            return result[0]["widgets"]
        return []

    # ── Command History ───────────────────────────────────

    async def log_command(self, text):
        """Append a command to history."""
        if not self.db:
            return
        await self.db.query(
            "CREATE history SET text = $text, ts = time::now()",
            {"text": text},
        )

    async def get_history(self, limit=50):
        """Get recent command history."""
        if not self.db:
            return []
        result = await self.db.query(
            "SELECT text, ts FROM history ORDER BY ts DESC LIMIT $limit",
            {"limit": limit},
        )
        return result if result else []
