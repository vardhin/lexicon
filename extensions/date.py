"""
Date extension — shows the current date.
"""

import re
import uuid


def match(text):
    patterns = [
        r"what'?s?\s+the\s+date",
        r"show\s+(me\s+)?(the\s+)?date",
        r"current\s+date",
        r"today'?s?\s+date",
        r"^date$",
        r"what\s+day\s+is\s+(it|today)",
    ]
    for p in patterns:
        if re.search(p, text):
            return True
    return None


def action(original_text, match_result):
    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"date-{uuid.uuid4().hex[:6]}",
        "widget_type": "date",
        "x": 50,
        "y": 260,
        "w": 320,
        "h": 200,
        "props": {},
    }


EXTENSION = {
    "name": "date",
    "match": match,
    "action": action,
    "help": {
        "title": "Date",
        "icon": "📅",
        "description": "Today's date with year progress",
        "examples": ["date", "what's the date", "what day is it"],
    },
}
