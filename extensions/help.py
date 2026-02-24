"""
Help extension — shows all available commands and how to use them.
"""

import re
import uuid


def match(text):
    patterns = [
        r"^help$",
        r"^commands$",
        r"^what\s+can\s+you\s+do",
        r"^show\s+(me\s+)?help",
        r"^how\s+do\s+i\s+use",
        r"^list\s+(commands|widgets|extensions)",
        r"^\?$",
    ]
    for p in patterns:
        if re.search(p, text):
            return True
    return None


def action(original_text, match_result):
    # props.entries will be injected by main.py from engine.get_help_entries()
    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"help-{uuid.uuid4().hex[:6]}",
        "widget_type": "help",
        "x": 100,
        "y": 60,
        "w": 420,
        "h": 480,
        "props": {},
    }


EXTENSION = {
    "name": "help",
    "match": match,
    "action": action,
    "help": {
        "title": "Help",
        "icon": "❓",
        "description": "Show this help guide",
        "examples": ["help", "commands", "?"],
    },
}
