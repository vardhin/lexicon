"""
Organ Manager — extension to open the organ management widget.

The Organ Manager lets you:
  - Create new organs from any URL (each organ = a browser tab)
  - Launch/kill organ tabs
  - Paste outer HTML patterns → name them → scrape all matching elements
  - View scraped data stored in Memory

Usage:
  "organs"
  "organ manager"
  "scrape"
  "new organ"
"""

import re
import uuid

_patterns = [
    re.compile(r'\b(organ|organs)\b', re.IGNORECASE),
    re.compile(r'\b(scrape|scraper|scraping)\b', re.IGNORECASE),
    re.compile(r'\bnew\s*organ\b', re.IGNORECASE),
    re.compile(r'\bpattern\s*(match|matcher)\b', re.IGNORECASE),
]


def match(text):
    for p in _patterns:
        if p.search(text):
            return True
    return None


def action(text, match_result):
    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"organmgr-{uuid.uuid4().hex[:6]}",
        "widget_type": "organmanager",
        "x": 40,
        "y": 40,
        "w": 700,
        "h": 600,
        "props": {},
    }


EXTENSION = {
    "name": "organmanager",
    "match": match,
    "action": action,
    "help": {
        "title": "Organ Manager",
        "icon": "🧬",
        "description": "Manage organs — open any URL as a tab, paste HTML patterns to scrape matching elements",
        "examples": ["organs", "organ manager", "scrape", "new organ"],
    },
}
