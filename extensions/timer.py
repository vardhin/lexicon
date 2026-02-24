"""
Timer extension — countdown timer widget.
Matches: "timer 5 min", "set timer 30s", "countdown 10 minutes", "timer 1h30m"
"""

import re
import uuid


def match(text):
    """Match timer-related commands. Returns parsed seconds or None."""
    patterns = [
        r"(?:set\s+)?(?:a\s+)?timer\s+(?:for\s+)?(.+)",
        r"countdown\s+(?:for\s+)?(.+)",
        r"^(\d+\s*(?:s|sec|seconds?|m|min|minutes?|h|hours?|hr).*)$",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return _parse_duration(m.group(1).strip())
    return None


def _parse_duration(s):
    """Parse a duration string into seconds. Returns int or None."""
    total = 0
    found = False

    # "1h30m10s" or "1h 30m 10s"
    for val, unit in re.findall(r"(\d+)\s*(h|hr|hours?|m|min|minutes?|s|sec|seconds?)", s):
        found = True
        n = int(val)
        if unit.startswith("h"):
            total += n * 3600
        elif unit.startswith("m"):
            total += n * 60
        else:
            total += n

    if found and total > 0:
        return total

    # bare number → treat as minutes
    m = re.match(r"^(\d+)$", s.strip())
    if m:
        return int(m.group(1)) * 60

    return None


def action(original_text, seconds):
    """Return a RENDER_WIDGET action for the timer."""
    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"timer-{uuid.uuid4().hex[:6]}",
        "widget_type": "timer",
        "x": 400,
        "y": 50,
        "w": 320,
        "h": 200,
        "props": {"seconds": seconds},
    }


EXTENSION = {
    "name": "timer",
    "match": match,
    "action": action,
    "help": {
        "title": "Timer",
        "icon": "⏱",
        "description": "Countdown timer with pause/resume",
        "examples": ["timer 5 min", "countdown 1h30m", "set timer 30s"],
    },
}
