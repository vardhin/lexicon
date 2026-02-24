"""
Clear extension — clears all widgets from screen.
"""

import re


def match(text):
    patterns = [
        r"^(clear|dismiss|close|hide)(\s+all)?$",
        r"clear\s+(widgets|screen|everything)",
        r"dismiss\s+(all|widgets|everything)",
    ]
    for p in patterns:
        if re.search(p, text):
            return True
    return None


def action(original_text, match_result):
    return {"type": "CLEAR_WIDGETS"}


EXTENSION = {
    "name": "clear",
    "match": match,
    "action": action,
    "help": {
        "title": "Clear",
        "icon": "🧹",
        "description": "Dismiss all widgets from the screen",
        "examples": ["clear", "dismiss all", "close all"],
    },
}
