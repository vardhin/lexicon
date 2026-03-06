"""
Automation — extension to manage and run organ automations.

Automations are programmable action sequences that dynamically crawl
through Playwright tabs: click, scroll, navigate, type, wait, paginate,
and extract data — all composable into saved workflows.

Usage:
  "automations"            → Open the automation manager widget
  "automate"               → Same
  "run automation X on Y"  → (future) Run automation X on organ Y
  "crawl"                  → Open automation manager
"""

import re
import uuid

_patterns = [
    re.compile(r'\b(automat|automation|automations)\b', re.IGNORECASE),
    re.compile(r'\b(crawl|crawler|crawling)\b', re.IGNORECASE),
    re.compile(r'\bautomate\b', re.IGNORECASE),
    re.compile(r'\bworkflow\b', re.IGNORECASE),
    re.compile(r'\bbot\s*(run|action)?\b', re.IGNORECASE),
]


def match(text):
    for p in _patterns:
        if p.search(text):
            return True
    return None


def action(text, match_result):
    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"automation-{uuid.uuid4().hex[:6]}",
        "widget_type": "automation",
        "x": 60,
        "y": 60,
        "w": 750,
        "h": 650,
        "props": {},
    }


EXTENSION = {
    "name": "automation",
    "match": match,
    "action": action,
    "help": {
        "title": "Automation",
        "icon": "🤖",
        "description": "Programmable browser automation — click, scroll, navigate, type, extract data across pages",
        "examples": ["automations", "automate", "crawl", "workflow"],
    },
}
