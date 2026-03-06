"""
Theme extension — apply, list, and reset visual themes via natural language.

Usage:
  "theme cyberpunk"     → apply the 'cyberpunk' theme
  "theme midnight"      → apply the 'midnight' theme
  "themes"              → list all available themes
  "list themes"         → list all available themes
  "reset theme"         → revert to default (no theme)
  "default theme"       → revert to default (no theme)
"""

import re

_apply_re = re.compile(
    r"^(?:theme|skin|style)\s+(.+)$",
    re.IGNORECASE,
)

_list_re = re.compile(
    r"^(?:themes|list\s+themes?|show\s+themes?|available\s+themes?)$",
    re.IGNORECASE,
)

_reset_re = re.compile(
    r"^(?:reset\s+theme|default\s+theme|clear\s+theme|no\s+theme|remove\s+theme)$",
    re.IGNORECASE,
)


def match(text):
    text = text.strip()
    if _reset_re.match(text):
        return ("reset", None)
    if _list_re.match(text):
        return ("list", None)
    m = _apply_re.match(text)
    if m:
        name = m.group(1).strip().lower().replace(" ", "-")
        if name in ("list", "show", "all", "available"):
            return ("list", None)
        if name in ("reset", "default", "clear", "none", "remove"):
            return ("reset", None)
        return ("apply", name)
    return None


def action(original_text, match_result):
    op, name = match_result

    if op == "reset":
        return {
            "type": "THEME_RESET",
        }

    if op == "list":
        return {
            "type": "THEME_LIST_REQUEST",
        }

    # op == "apply"
    return {
        "type": "THEME_APPLY",
        "name": name,
    }


EXTENSION = {
    "name": "theme",
    "match": match,
    "action": action,
    "help": {
        "title": "Themes",
        "icon": "🎨",
        "description": "Change the visual style of the entire overlay",
        "examples": ["theme cyberpunk", "themes", "reset theme"],
    },
}
