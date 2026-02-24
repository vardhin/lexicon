"""
Note extension — creates a sticky note widget.
Matches: "note buy groceries", "remind me to call bob", "memo meeting at 3"
"""

import re
import uuid


def match(text):
    patterns = [
        r"^note\s+(.+)",
        r"^memo\s+(.+)",
        r"^remind\s+(?:me\s+)?(?:to\s+)?(.+)",
        r"^sticky\s+(.+)",
        r"^jot\s+(?:down\s+)?(.+)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return None


def action(original_text, note_text):
    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"note-{uuid.uuid4().hex[:6]}",
        "widget_type": "note",
        "x": 750,
        "y": 50,
        "w": 280,
        "h": 180,
        "props": {"text": note_text},
    }


EXTENSION = {
    "name": "note",
    "match": match,
    "action": action,
    "help": {
        "title": "Note",
        "icon": "📝",
        "description": "Sticky note — click to edit text",
        "examples": ["note buy groceries", "remind me to call bob", "memo meeting at 3"],
    },
}
