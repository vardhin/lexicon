"""
Person — extension to display resolved entity (person) nodes.

Opens the PersonWidget, which shows either:
  - A searchable grid of all resolved people (list mode)
  - A single person's full profile card (detail mode)

Supports management commands:
  - Delete a specific person by name or entity ID
  - Clear all people from the knowledge graph

Usage:
  "people"              → show all resolved person nodes
  "person Rishi"        → search for a specific person
  "contacts"            → alias for people
  "who is Rishi"        → search by name
  "entity <id>"         → show specific entity by ID
  "delete person Rishi" → delete a person by name
  "delete entity <id>"  → delete a specific entity by ID
  "clear people"        → delete all people
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

# ── Delete / clear patterns ──

_delete_entity_re = re.compile(
    r'^(?:delete|remove|rm)\s+entity\s+([a-f0-9]+)$',
    re.IGNORECASE,
)

_delete_person_re = re.compile(
    r'^(?:delete|remove|rm|forget)\s+(?:person|contact|people)\s+(.+)$',
    re.IGNORECASE,
)

_clear_re = re.compile(
    r'^(?:clear|reset|wipe|delete\s+all|remove\s+all)\s+'
    r'(?:people|persons|contacts|entities)$',
    re.IGNORECASE,
)


def match(text):
    text = text.strip()

    # Clear all people (check first — more specific than list)
    if _clear_re.match(text):
        return {'mode': 'clear'}

    # Delete entity by ID
    m = _delete_entity_re.match(text)
    if m:
        return {'mode': 'delete_entity', 'entity_id': m.group(1)}

    # Delete person by name
    m = _delete_person_re.match(text)
    if m:
        query = m.group(1).strip()
        if query:
            return {'mode': 'delete_person', 'query': query}

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

    # ── Clear all entities ──
    if mode == 'clear':
        return {
            "type": "ENTITY_CLEAR",
        }

    # ── Delete by entity ID ──
    if mode == 'delete_entity':
        return {
            "type": "ENTITY_DELETE",
            "entity_id": match_result['entity_id'],
        }

    # ── Delete by person name (search + delete) ──
    if mode == 'delete_person':
        return {
            "type": "ENTITY_DELETE_BY_NAME",
            "query": match_result['query'],
        }

    # ── Detail view ──
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

    # ── Search view ──
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
        "description": "View, search, and manage resolved person nodes — cross-source identity graph",
        "examples": [
            "people",
            "person Rishi",
            "who is Mehta",
            "contacts",
            "delete person Rishi",
            "clear people",
        ],
    },
}
