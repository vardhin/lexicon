"""
Weather extension — weather display widget (placeholder/demo).
In a real setup, this would call a weather API.
"""

import re
import uuid


def match(text):
    patterns = [
        r"^weather$",
        r"show\s+(me\s+)?(the\s+)?weather",
        r"what'?s?\s+the\s+weather",
        r"^forecast$",
        r"how'?s?\s+the\s+weather",
        r"weather\s+(today|now|forecast)",
        r"is\s+it\s+(raining|sunny|cold|hot|warm)",
    ]
    for p in patterns:
        if re.search(p, text):
            return True
    return None


def action(original_text, match_result):
    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"weather-{uuid.uuid4().hex[:6]}",
        "widget_type": "weather",
        "x": 750,
        "y": 260,
        "w": 280,
        "h": 220,
        "props": {},
    }


EXTENSION = {
    "name": "weather",
    "match": match,
    "action": action,
    "help": {
        "title": "Weather",
        "icon": "🌤",
        "description": "Weather display (demo — connect API for real data)",
        "examples": ["weather", "forecast", "is it raining"],
    },
}
