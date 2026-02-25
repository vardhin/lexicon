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

    # ── WhatsApp Contacts & Messages ────────────────────

    async def ensure_whatsapp_contact(self, name: str) -> str:
        """Create a contact node if it doesn't exist. Returns the contact ID."""
        if not self.db:
            return name
        # Check if contact already exists
        result = await self.db.query(
            "SELECT * FROM whatsapp_contact WHERE name = $name",
            {"name": name},
        )
        if result and len(result) > 0:
            rid = result[0].get("id", name)
            return str(rid)
        # Create new contact node
        await self.db.query(
            "CREATE whatsapp_contact SET name = $name, "
            "first_seen = time::now(), last_seen = time::now(), "
            "message_count = 0",
            {"name": name},
        )
        return name

    async def store_whatsapp_message(self, contact: str, chat: str, text: str,
                                      timestamp: str, message_id: str,
                                      unread_count: int = 0):
        """Store a WhatsApp message and update the contact node."""
        if not self.db:
            return

        # Ensure contact exists
        await self.ensure_whatsapp_contact(contact)

        # Check if this exact message was already stored (dedup)
        existing = await self.db.query(
            "SELECT * FROM whatsapp_message WHERE message_id = $mid",
            {"mid": message_id},
        )
        if existing and len(existing) > 0:
            return  # Already stored

        # Store the message
        await self.db.query(
            "CREATE whatsapp_message SET "
            "contact = $contact, chat = $chat, text = $text, "
            "timestamp = $ts, message_id = $mid, "
            "unread_count = $unread, received_at = time::now()",
            {
                "contact": contact,
                "chat": chat,
                "text": text,
                "ts": timestamp,
                "mid": message_id,
                "unread": unread_count,
            },
        )

        # Update contact's last_seen and increment message count
        await self.db.query(
            "UPDATE whatsapp_contact SET last_seen = time::now(), "
            "message_count = message_count + 1 "
            "WHERE name = $name",
            {"name": contact},
        )

    async def get_whatsapp_messages(self, contact: str = None, limit: int = 50):
        """Get recent WhatsApp messages, optionally filtered by contact."""
        if not self.db:
            return []

        if contact:
            result = await self.db.query(
                "SELECT * FROM whatsapp_message WHERE contact = $contact "
                "ORDER BY received_at DESC LIMIT $limit",
                {"contact": contact, "limit": limit},
            )
        else:
            result = await self.db.query(
                "SELECT * FROM whatsapp_message "
                "ORDER BY received_at DESC LIMIT $limit",
                {"limit": limit},
            )

        if not result:
            return []

        sanitized = _sanitize_for_json(result)
        return list(reversed(sanitized))

    async def get_whatsapp_contacts(self):
        """Get all known WhatsApp contacts with their message counts."""
        if not self.db:
            return []
        result = await self.db.query(
            "SELECT name, message_count, last_seen, first_seen "
            "FROM whatsapp_contact ORDER BY last_seen DESC"
        )
        if not result:
            return []
        return _sanitize_for_json(result)

    async def get_whatsapp_chats_summary(self, limit: int = 20):
        """Get a summary of recent chats — last message per chat/conversation."""
        if not self.db:
            return []
        # Get the latest message per chat (conversation name, not sender)
        result = await self.db.query(
            "SELECT contact, chat, text, timestamp, received_at, unread_count "
            "FROM whatsapp_message "
            "ORDER BY received_at DESC LIMIT $limit",
            {"limit": limit * 3},  # Over-fetch, then deduplicate
        )
        if not result:
            return []

        # Sanitize first, then deduplicate
        sanitized = _sanitize_for_json(result)

        # Deduplicate by chat (conversation name) — keep only the latest message
        seen_chats = {}
        for row in sanitized:
            chat_key = row.get("chat") or row.get("contact", "")
            if chat_key not in seen_chats:
                entry = dict(row)
                entry["chat"] = chat_key
                seen_chats[chat_key] = entry
            if len(seen_chats) >= limit:
                break

        return list(seen_chats.values())
