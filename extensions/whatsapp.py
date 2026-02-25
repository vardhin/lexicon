"""
WhatsApp extension — shows WhatsApp messages from the organ tab.

Triggers on whatsapp/messages/chats keywords.
Renders a WhatsApp dashboard widget on the overlay showing
messages received from the WhatsApp organ tab (a real web.whatsapp.com
webview running in a separate Tauri window).
"""

import re
import uuid


def match(text):
    """Return True if text asks about WhatsApp / messages / chats."""
    patterns = [
        r"\bwhatsapp\b",
        r"\bmessages?\b",
        r"\bchats?\b",
        r"\bwho\s+(texted|messaged|wrote)\b",
        r"\bunread\b",
        r"\binbox\b",
        r"\bshow\s+(me\s+)?(my\s+)?messages\b",
        r"\bany\s+(new\s+)?messages\b",
    ]
    for p in patterns:
        if re.search(p, text):
            return True
    return None


def action(original_text, match_result):
    """Return a RENDER_WIDGET action for the WhatsApp chat widget."""
    # Check if user is asking about a specific contact
    contact = None
    m = re.search(
        r"(?:from|by|with)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)",
        original_text,
    )
    if m:
        contact = m.group(1).strip()

    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"whatsapp-{uuid.uuid4().hex[:6]}",
        "widget_type": "whatsapp",
        "x": 50,
        "y": 50,
        "w": 420,
        "h": 520,
        "props": {
            "filter_contact": contact,
        },
    }


EXTENSION = {
    "name": "whatsapp",
    "match": match,
    "action": action,
    "help": {
        "title": "WhatsApp",
        "icon": "💬",
        "description": "View WhatsApp messages — switch to the WhatsApp tab to log in",
        "examples": [
            "whatsapp",
            "messages",
            "show my chats",
            "any new messages",
            "messages from John",
        ],
    },
}
