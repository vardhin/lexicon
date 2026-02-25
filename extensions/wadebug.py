"""
WhatsApp DOM Debug — extension to open the WA DOM inspector widget.

Usage:
  "wa debug"
  "whatsapp debug"
  "whatsapp dom"
  "wa inspect"
"""

import re
import uuid

_patterns = [
    re.compile(r'\b(wa|whatsapp)\s+(debug|inspect|dom|selectors?)\b', re.IGNORECASE),
    re.compile(r'\bdebug\s+(wa|whatsapp)\b', re.IGNORECASE),
]


def match(text):
    for p in _patterns:
        if p.search(text):
            return True
    return None


def action(text, match_result):
    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"wadebug-{uuid.uuid4().hex[:6]}",
        "widget_type": "wadebug",
        "x": 60,
        "y": 50,
        "w": 600,
        "h": 550,
        "props": {},
    }


EXTENSION = {
    "name": "wadebug",
    "match": match,
    "action": action,
    "help": {
        "title": "WA Debug",
        "icon": "🔍",
        "description": "WhatsApp DOM inspector — browse the DOM tree, test CSS selectors, see what the monitor identifies",
        "examples": ["wa debug", "whatsapp dom", "wa inspect"],
    },
}
