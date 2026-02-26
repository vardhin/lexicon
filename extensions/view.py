"""
Data View — extension to display scraped organ data in a beautiful layout.

Renders a DataViewWidget that auto-fetches data from a named organ
and displays it using the recursive card/grid/list primitives.

You can also pass a fully custom layout tree via props.layout for
programmatic dashboards.

Usage:
  "view github"        → show scraped data from the 'github' organ
  "view whatsapp"      → show scraped data from the 'whatsapp' organ
  "dashboard"          → show all data from all organs
  "show data"          → show all data from all organs
"""

import re
import uuid

# Match patterns:
#   "view <organ_id>"
#   "show <organ_id> data"
#   "dashboard"
#   "show data"

_view_re = re.compile(
    r'^(?:view|display)\s+(.+)$',
    re.IGNORECASE,
)
_dashboard_re = re.compile(
    r'^(?:dashboard|show\s+(?:all\s+)?data|render\s+data)$',
    re.IGNORECASE,
)


def match(text):
    text = text.strip()
    # "dashboard" or "show data" → all organs
    m2 = _dashboard_re.match(text)
    if m2:
        return '__all__'
    # "view github" / "display whatsapp" → specific organ
    m = _view_re.match(text)
    if m:
        organ = m.group(1).strip().rstrip(' data').strip()
        return organ if organ else None
    return None


def action(text, match_result):
    organ_id = match_result

    if organ_id == '__all__':
        # Dashboard mode — show data from all organs.
        # The widget will build a layout by fetching from all organs.
        return {
            "type": "RENDER_WIDGET",
            "widget_id": f"dv-all-{uuid.uuid4().hex[:6]}",
            "widget_type": "dataview",
            "x": 40,
            "y": 40,
            "w": 680,
            "h": 520,
            "props": {
                "title": "📊 All Scraped Data",
                "organ_id": None,
                "layout": None,  # Widget will fetch all
                "auto_refresh": False,
            },
        }

    # Specific organ
    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"dv-{organ_id}-{uuid.uuid4().hex[:6]}",
        "widget_type": "dataview",
        "x": 40,
        "y": 40,
        "w": 640,
        "h": 480,
        "props": {
            "title": f"📊 {organ_id}",
            "organ_id": organ_id,
            "auto_refresh": True,
            "refresh_interval": 15000,
        },
    }


EXTENSION = {
    "name": "dataview",
    "match": match,
    "action": action,
    "help": {
        "title": "Data View",
        "icon": "📊",
        "description": "Display scraped organ data as beautiful cards, grids, and lists",
        "examples": [
            "view github",
            "view whatsapp",
            "dashboard",
            "show data",
        ],
    },
}
