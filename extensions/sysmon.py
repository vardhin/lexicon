"""
System monitor extension — shows live CPU/RAM/disk usage.
Uses /proc for zero-dependency monitoring.
"""

import re
import uuid


def match(text):
    patterns = [
        r"^(system|sysmon|sys)(\s+monitor)?$",
        r"show\s+(me\s+)?(system|stats|resources|cpu|ram|memory)",
        r"^(stats|resources|htop|top)$",
        r"how'?s?\s+(the\s+)?(system|cpu|ram|memory)",
        r"^monitor$",
    ]
    for p in patterns:
        if re.search(p, text):
            return True
    return None


def action(original_text, match_result):
    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"sysmon-{uuid.uuid4().hex[:6]}",
        "widget_type": "sysmon",
        "x": 50,
        "y": 490,
        "w": 360,
        "h": 240,
        "props": {},
    }


EXTENSION = {
    "name": "sysmon",
    "match": match,
    "action": action,
    "help": {
        "title": "System Monitor",
        "icon": "📊",
        "description": "Live CPU, RAM, and disk usage bars",
        "examples": ["system", "show stats", "monitor"],
    },
}
