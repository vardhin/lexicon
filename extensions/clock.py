"""
Clock extension — triggers on time/clock keywords.
Tells the frontend to render a clock widget.
"""

import re
import uuid


def match(text):
    """Return True if text asks for the time, else None."""
    patterns = [
        r"what'?s?\s+the\s+time",
        r"show\s+(me\s+)?(the\s+)?time",
        r"current\s+time",
        r"time\s+now",
        r"^clock$",
        r"show\s+(me\s+)?(the\s+)?clock",
        r"what\s+time\s+is\s+it",
    ]
    for p in patterns:
        if re.search(p, text):
            return True
    return None


def action(original_text, match_result):
    """Return a RENDER_WIDGET action for the clock."""
    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"clock-{uuid.uuid4().hex[:6]}",
        "widget_type": "clock",
        "x": 50,
        "y": 50,
        "w": 320,
        "h": 180,
        "props": {"format": "24h", "show_seconds": True},
    }


EXTENSION = {
    "name": "clock",
    "match": match,
    "action": action,
}
