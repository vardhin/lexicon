"""
Person — extension to display resolved entity (person) nodes.

Opens the PersonWidget, which shows either:
  - A searchable grid of all resolved people (list mode)
  - A single person's full profile card (detail mode)

Usage:
  "people"              → show all resolved person nodes
  "person Rishi"        → search for a specific person
  "contacts"            → alias for people
  "who is Rishi"        → search by name
  "entity <id>"         → show specific entity by ID
"""

import re
import uuid

_list_re = re.compile(
    r'^(?:people|persons|contacts|entities|who do i know|'
    r'show\s+(?:all\s+)?(?:people|persons|contacts|entities)|'
    r'person\s+(?:list|all)|'
    r'knowledge\s+graph)$',
    re.IGNORECASE,
)

_search_re = re.compile(
    r'^(?:person|who\s+is|find\s+person|search\s+person|lookup|find)\s+(.+)$',
    re.IGNORECASE,
)

_entity_re = re.compile(
    r'^entity\s+([a-f0-9]+)$',
    re.IGNORECASE,
)


def match(text):
    text = text.strip()

    # List mode
    if _list_re.match(text):
        return {'mode': 'list'}

    # Specific entity by ID
    m = _entity_re.match(text)
    if m:
        return {'mode': 'detail', 'entity_id': m.group(1)}

    # Search mode
    m = _search_re.match(text)
    if m:
        query = m.group(1).strip()
        if query:
            return {'mode': 'search', 'query': query}

    return None


def action(text, match_result):
    mode = match_result.get('mode', 'list')

    if mode == 'detail':
        entity_id = match_result['entity_id']
        return {
            "type": "RENDER_WIDGET",
            "widget_id": f"person-{entity_id[:8]}",
            "widget_type": "person",
            "x": 60, "y": 60, "w": 480, "h": 560,
            "props": {
                "entity_id": entity_id,
                "title": "👤 Person",
                "auto_refresh": False,
            },
        }

    if mode == 'search':
        query = match_result['query']
        return {
            "type": "RENDER_WIDGET",
            "widget_id": f"person-search-{uuid.uuid4().hex[:6]}",
            "widget_type": "person",
            "x": 40, "y": 40, "w": 680, "h": 520,
            "props": {
                "title": f"👥 People — \"{query}\"",
                "search_query": query,
                "auto_refresh": False,
            },
        }

    # List mode (default)
    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"person-list-{uuid.uuid4().hex[:6]}",
        "widget_type": "person",
        "x": 40, "y": 40, "w": 720, "h": 560,
        "props": {
            "title": "👥 People",
            "auto_refresh": True,
            "refresh_interval": 15000,
        },
    }


EXTENSION = {
    "name": "person",
    "match": match,
    "action": action,
    "help": {
        "title": "People",
        "icon": "👥",
        "description": "View resolved person nodes from scraped data — cross-source identity graph",
        "examples": [
            "people",
            "person Rishi",
            "who is Mehta",
            "contacts",
            "entities",
        ],
    },
}
