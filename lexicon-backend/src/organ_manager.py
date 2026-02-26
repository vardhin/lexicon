"""
Organ Manager — Playwright-based browser controller for Lexicon organs.

Architecture:
  A SINGLE headed Chromium browser runs off-screen (--window-position=-2400,-2400).
  Each organ is a TAB in that browser. The browser is persistent (cookies/sessions
  survive restarts via user_data_dir). The browser is "headed" (not headless) so
  sites like WhatsApp see a real browser — but it's positioned off-screen so it
  never appears on the user's desktop.

  Deep Structural Scraping:
    The user pastes an outer HTML snippet from their browser and names it.
    We parse the FULL nested HTML tree (not just the root tag) to discover:
      1. The root tag fingerprint (for finding similar container elements)
      2. All meaningful inner "fields" — text in links/spans/headings,
         image URLs, timestamps, language labels, etc.
    Each field gets a CSS selector path (relative to the container) and an
    auto-generated human-readable label. When scraping, each matched
    container yields a structured OBJECT (not flat text), e.g.:
      { "user": "alice", "repo": "myproject", "language": "Python",
        "avatar": "https://...", "time": "Feb 24" }

    This means deeply nested divs-in-divs-in-divs are handled naturally —
    the tree parser walks the whole structure and picks out the leaf data.

Usage:
  The OrganManager is started during Brain lifespan and exposes methods
  that the FastAPI endpoints call directly.
"""

import asyncio
import json as _json
import os
import re
from datetime import datetime
from typing import Optional
from html.parser import HTMLParser

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


# Where persistent browser data lives (cookies, localStorage, etc.)
USER_DATA_DIR = os.path.expanduser("~/.local/share/lexicon/organs/browser_data")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  HTML TREE PARSER — builds a full DOM-like tree from HTML
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class _TreeNode:
    """A simple DOM tree node for structural analysis."""
    __slots__ = ('tag', 'attrs', 'classes', 'children', 'text', 'parent', 'depth')

    def __init__(self, tag, attrs=None, parent=None, depth=0):
        self.tag = tag.lower() if tag else ''
        self.attrs = dict(attrs) if attrs else {}
        self.classes = []
        cls = self.attrs.get('class', '')
        if cls:
            self.classes = [c.strip() for c in cls.split() if c.strip()]
        self.children = []
        self.text = ''
        self.parent = parent
        self.depth = depth


class _TreeBuilder(HTMLParser):
    """Parse HTML into a tree of _TreeNode objects."""

    # Tags that are self-closing and never have children
    VOID_TAGS = frozenset([
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr',
    ])

    def __init__(self):
        super().__init__()
        self.root = None
        self._current = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        node = _TreeNode(tag, attrs, parent=self._current, depth=self._depth)
        if self.root is None:
            self.root = node
        if self._current is not None:
            self._current.children.append(node)
        if tag not in self.VOID_TAGS:
            self._current = node
            self._depth += 1
        else:
            # Void tags are leaf nodes attached to current parent
            if self._current is None:
                self.root = node

    def handle_endtag(self, tag):
        if self._current is not None and self._current.tag == tag.lower():
            self._current = self._current.parent
            self._depth -= 1

    def handle_data(self, data):
        text = data.strip()
        if text and self._current is not None:
            if self._current.text:
                self._current.text += ' ' + text
            else:
                self._current.text = text

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def _parse_html_tree(html: str) -> Optional[_TreeNode]:
    """Parse HTML string into a tree. Returns root node or None."""
    builder = _TreeBuilder()
    try:
        builder.feed(html)
    except Exception:
        pass
    return builder.root


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FIELD DISCOVERY — walk the tree and find meaningful data
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Tags whose text content is usually meaningful
_TEXT_TAGS = frozenset([
    'a', 'span', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'label', 'button', 'li', 'td', 'th', 'strong', 'em', 'b', 'i',
    'small', 'time', 'relative-time', 'code', 'pre', 'figcaption',
])

# Tags that carry data in attributes, not text
_ATTR_TAGS = {
    'img': 'src',
    'a': 'href',
    'relative-time': 'datetime',
    'time': 'datetime',
    'input': 'value',
}

# Attributes that are just noise (tracking, hydro, etc.)
_NOISE_ATTRS = frozenset([
    'data-hydro-click', 'data-hydro-click-hmac', 'data-hovercard-url',
    'data-octo-click', 'data-octo-dimensions', 'data-octo-click',
    'data-ga-click', 'data-close-dialog-id', 'data-show-dialog-id',
    'data-csrf', 'data-turbo',
])

# Classes/tags that signal "this is just chrome, not data"
_SKIP_CLASSES = frozenset([
    'sr-only', 'octicon', 'SelectMenu', 'Overlay', 'ActionListWrap',
    'js-toggler-container', 'js-social-container', 'js-social-form',
    'details-reset', 'details-overlay', 'BtnGroup', 'BtnGroup-parent',
    'SelectMenu-modal', 'SelectMenu-list', 'SelectMenu-loading',
    'blankslate', 'Overlay-header', 'Overlay-body',
    'js-feed-item-disinterest-dialog', 'js-feed-disinterest-submit',
    'disinterest-modal',
])

_SKIP_TAGS = frozenset([
    'svg', 'path', 'circle', 'script', 'style', 'template',
    'dialog', 'anchored-position', 'action-menu', 'action-list',
    'include-fragment', 'focus-group', 'tool-tip', 'scrollable-region',
    'dialog-helper', 'disinterest-modal', 'form',
])


def _should_skip(node: _TreeNode) -> bool:
    """Should this subtree be skipped entirely?"""
    if node.tag in _SKIP_TAGS:
        return True
    # Skip if it has skip-indicating classes
    for c in node.classes:
        if c in _SKIP_CLASSES:
            return True
    # Skip hidden elements
    if node.attrs.get('hidden') is not None or node.attrs.get('aria-hidden') == 'true':
        # Exception: don't skip the root node itself
        if node.depth > 0:
            return True
    return False


def _auto_label(node: _TreeNode, path_parts: list) -> str:
    """Generate a human-readable field label from context clues."""
    tag = node.tag

    # Use aria-label if available
    aria = node.attrs.get('aria-label', '').strip()
    if aria and len(aria) < 40:
        return re.sub(r'[^a-z0-9]+', '_', aria.lower()).strip('_')[:30]

    # Hovercard type hints
    hc = node.attrs.get('data-hovercard-type', '')
    if hc:
        return hc

    # itemprop gives an explicit semantic hint
    itemprop = node.attrs.get('itemprop', '')
    if itemprop:
        return re.sub(r'[^a-z0-9]+', '_', itemprop.lower()).strip('_')[:30]

    # Tag-based labels
    if tag == 'img':
        alt = node.attrs.get('alt', '')
        if 'avatar' in alt.lower() or 'avatar' in ' '.join(node.classes).lower():
            return 'avatar'
        if 'profile' in alt.lower():
            return 'avatar'
        return 'image'
    if tag in ('relative-time', 'time'):
        return 'time'
    if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        # Check for muted/meta headings vs real headings
        cls_str = ' '.join(node.classes).lower()
        if 'color-fg-muted' in cls_str or 'text-small' in cls_str:
            return 'meta'
        return 'heading'

    # Class-based hints
    cls_str = ' '.join(node.classes).lower()
    if 'avatar' in cls_str:
        return 'avatar'
    if 'language' in cls_str or 'repo-language' in cls_str:
        return 'language'
    if 'text-bold' in cls_str or 'link--primary' in cls_str:
        return 'title'
    if 'color-fg-muted' in cls_str and tag in ('h4', 'h3', 'span', 'div'):
        return 'meta'

    # Check parent's aria-label for context (e.g. section aria-label="Repo Details")
    if node.parent:
        parent_aria = node.parent.attrs.get('aria-label', '').lower()
        if 'repo' in parent_aria:
            return 'repo_info'
        if 'detail' in parent_aria:
            return 'detail'

    # Fall back to tag name or last meaningful path part
    if tag == 'a':
        href = node.attrs.get('href', '')
        if href and not href.startswith('#') and not href.startswith('javascript'):
            return 'link'
    if tag == 'span':
        # Use a parent hint if possible
        if path_parts:
            last = path_parts[-1]
            if last and last != 'div' and last != 'span':
                return last
        return 'text'

    return tag


def _build_css_path(node: _TreeNode, root: _TreeNode) -> str:
    """Build a CSS selector path from root to this node.
    Uses classes and tag to make it specific enough."""
    parts = []
    current = node
    while current is not None and current is not root:
        selector = current.tag
        # Use up to 2 most specific classes
        useful_classes = [c for c in current.classes
                          if not c.startswith('js-') and len(c) < 40]
        if useful_classes:
            selector += '.' + '.'.join(useful_classes[:2])
        parts.append(selector)
        current = current.parent
    parts.reverse()
    return ' > '.join(parts) if parts else ''


def discover_fields(html: str) -> dict:
    """Analyze an HTML snippet and discover all extractable fields.

    Returns: {
        "fingerprint": { tag, classes, attrs },   # root element fingerprint
        "fields": [
            {
                "label": "user",          # human-readable name
                "css_path": "div.flex-1 > h3 > span > a.Link--primary",
                "extract": "text",        # "text", "src", "href", "datetime"
                "example": "maanasvarma2003",
            },
            ...
        ],
    }
    """
    root = _parse_html_tree(html)
    if not root:
        return {"fingerprint": {"tag": "", "classes": [], "attrs": {}}, "fields": []}

    # Fingerprint = root element (same as before)
    fp = {
        "tag": root.tag,
        "classes": root.classes[:10],
        "attrs": {},
    }
    keep_attrs = [
        "role", "aria-label", "data-testid", "data-view-component",
        "data-hovercard-type", "type", "name", "data-tab",
        "aria-selected", "aria-expanded",
    ]
    for k in keep_attrs:
        if k in root.attrs and root.attrs[k]:
            fp["attrs"][k] = root.attrs[k]
    for k, v in root.attrs.items():
        if k.startswith("data-") and k not in _NOISE_ATTRS and v and len(v) < 100:
            fp["attrs"][k] = v

    # Walk tree and discover fields
    fields = []
    seen_labels = {}

    def walk(node, path_parts):
        if _should_skip(node):
            return

        is_leaf_text = (node.tag in _TEXT_TAGS and node.text and
                        len(node.text.strip()) > 0 and len(node.text.strip()) < 300)

        has_attr_data = node.tag in _ATTR_TAGS

        if is_leaf_text or has_attr_data:
            label = _auto_label(node, path_parts)
            css_path = _build_css_path(node, root)

            # Determine what to extract
            extract_type = 'text'
            example = (node.text or '').strip()[:100]

            if node.tag == 'img':
                extract_type = 'src'
                example = node.attrs.get('src', '')[:150]
            elif node.tag in ('relative-time', 'time'):
                extract_type = 'datetime'
                example = node.attrs.get('datetime', node.text or '')[:60]
            elif node.tag == 'a' and 'href' in node.attrs:
                # For links, extract both text and href
                href = node.attrs.get('href', '')
                if href and not href.startswith('#'):
                    # Add href as separate field
                    href_label = label + '_url' if label != 'link' else 'url'
                    if href_label not in seen_labels:
                        seen_labels[href_label] = True
                        fields.append({
                            "label": href_label,
                            "css_path": css_path,
                            "extract": "href",
                            "example": href[:150],
                        })

            # De-duplicate labels
            if label in seen_labels:
                count = seen_labels[label]
                seen_labels[label] = count + 1
                label = f"{label}_{count}"
            else:
                seen_labels[label] = 1

            if example and len(example) > 1:
                fields.append({
                    "label": label,
                    "css_path": css_path,
                    "extract": extract_type,
                    "example": example,
                })

        # Recurse into children
        tag_hint = node.tag if node.tag not in ('div', 'span') else ''
        for child in node.children:
            walk(child, path_parts + ([tag_hint] if tag_hint else []))

    walk(root, [])

    return {
        "fingerprint": fp,
        "fields": fields,
    }


def build_deep_match_js(fingerprint: dict, fields: list) -> str:
    """Build JavaScript that finds all matching containers AND extracts
    structured data from each one using the discovered field CSS paths.

    Three-stage pipeline (the "DAG"):
      Stage 1: SIMILARITY — find candidate containers by root-tag fingerprint
      Stage 2: STRUCTURAL VALIDATION — extract fields, reject elements where
               fewer than 40% of expected fields are present (kills sidebars,
               error dialogs, nav chrome)
      Stage 3: DEDUPLICATION — content-fingerprint each match, skip duplicates
               (kills GitHub's double/triple renders of the same card)

    Each surviving match returns a structured object like:
      { user: "alice", repo: "myproject", avatar: "https://...", ... }
    """
    tag = fingerprint.get("tag", "").lower()
    classes = fingerprint.get("classes", [])
    attrs = fingerprint.get("attrs", {})

    if not tag:
        return "(() => ({ error: 'no tag in fingerprint', matches: [] }))()"

    classes_json = _js_array(classes)
    attrs_json = _js_object(attrs)

    # Count how many fields we expect (for structural validation)
    total_fields = len(fields)

    # Build field extraction code
    field_extractors = []
    for f in fields:
        label = f["label"]
        css = f["css_path"]
        extract = f["extract"]

        # Escape for JS string
        css_escaped = css.replace("'", "\\'")
        label_escaped = label.replace("'", "\\'")

        if extract == 'text':
            field_extractors.append(
                f"        try {{ const _e = el.querySelector('{css_escaped}'); "
                f"if (_e) obj['{label_escaped}'] = (_e.textContent || '').trim().substring(0, 500); }} catch(_) {{}}"
            )
        elif extract == 'src':
            field_extractors.append(
                f"        try {{ const _e = el.querySelector('{css_escaped}'); "
                f"if (_e) obj['{label_escaped}'] = _e.getAttribute('src') || ''; }} catch(_) {{}}"
            )
        elif extract == 'href':
            field_extractors.append(
                f"        try {{ const _e = el.querySelector('{css_escaped}'); "
                f"if (_e) obj['{label_escaped}'] = _e.getAttribute('href') || ''; }} catch(_) {{}}"
            )
        elif extract == 'datetime':
            field_extractors.append(
                f"        try {{ const _e = el.querySelector('{css_escaped}'); "
                f"if (_e) obj['{label_escaped}'] = _e.getAttribute('datetime') || "
                f"(_e.textContent || '').trim(); }} catch(_) {{}}"
            )

    extractors_code = '\n'.join(field_extractors)

    return f"""
    (() => {{
        const TAG = {_js_string(tag)};
        const CLASSES = {classes_json};
        const ATTRS = {attrs_json};
        const EXPECTED_FIELDS = {total_fields};

        const totalSignals = 10 + CLASSES.length * 5 + Object.keys(ATTRS).length * 8;
        const threshold = Math.max(10, totalSignals * 0.35);

        // Stage 3 state: deduplication via content fingerprints
        const seenFingerprints = new Set();

        // Garbage patterns — reject values that are clearly not content
        const GARBAGE_RE = /^\\s*\\{{|^\\s*\\[|resolvedServerColorMode|data-hydro|Uh oh|reload this page|Skip to content|There was an error/i;

        const candidates = document.querySelectorAll(TAG);
        const results = [];

        for (let i = 0; i < candidates.length && results.length < 200; i++) {{
            const el = candidates[i];

            // ──── Stage 1: SIMILARITY (root tag fingerprint) ────
            let score = 10;

            const elClasses = el.className && typeof el.className === 'string'
                ? el.className.trim().split(/\\s+/) : [];
            const classSet = new Set(elClasses);
            for (const c of CLASSES) {{
                if (classSet.has(c)) score += 5;
            }}

            for (const [k, v] of Object.entries(ATTRS)) {{
                const av = el.getAttribute(k);
                if (av !== null) {{
                    if (av === v) score += 8;
                    else score += 3;
                }}
            }}

            if (score < threshold) continue;

            // ──── Stage 2: STRUCTURAL VALIDATION ────
            // Extract fields and count how many are actually present
            const obj = {{}};
{extractors_code}

            // Count populated fields (non-empty strings)
            const fieldKeys = Object.keys(obj);
            const populatedCount = fieldKeys.filter(k => {{
                const v = obj[k];
                return v && typeof v === 'string' && v.length > 0;
            }}).length;

            // Require at least 40% of expected fields to be present
            // (a sidebar or error dialog will have 0-1 out of 8 fields)
            const minFields = Math.max(2, Math.ceil(EXPECTED_FIELDS * 0.4));
            if (populatedCount < minFields) continue;

            // ──── Garbage filter ────
            // Check if any text field is JSON, error messages, or nav chrome
            let isGarbage = false;
            for (const k of fieldKeys) {{
                const v = obj[k];
                if (v && typeof v === 'string' && GARBAGE_RE.test(v)) {{
                    isGarbage = true;
                    break;
                }}
            }}
            if (isGarbage) continue;

            // ──── Stage 3: DEDUPLICATION ────
            // Build a content fingerprint from the field values
            // Two cards with the same user + same key content = duplicate
            const fpParts = [];
            for (const k of fieldKeys.sort()) {{
                const v = obj[k];
                if (v && typeof v === 'string') {{
                    // Normalize: lowercase, trim, collapse whitespace
                    fpParts.push(k + ':' + v.toLowerCase().trim().replace(/\\s+/g, ' ').substring(0, 80));
                }}
            }}
            const contentFP = fpParts.join('|');

            if (seenFingerprints.has(contentFP)) continue;
            seenFingerprints.add(contentFP);

            // ──── Survived all 3 stages — this is a real, unique match ────
            obj.__score = score;
            obj.__fieldRatio = populatedCount + '/' + EXPECTED_FIELDS;
            results.push(obj);
        }}

        results.sort((a, b) => (b.__score || 0) - (a.__score || 0));

        return {{
            threshold: threshold,
            totalSignals: totalSignals,
            expectedFields: EXPECTED_FIELDS,
            count: results.length,
            duplicatesSkipped: seenFingerprints.size > 0 ? (seenFingerprints.size - results.length) : 0,
            matches: results.slice(0, 100),
        }};
    }})()
    """


class OrganManager:
    """Manages a single headed Chromium browser with organs as tabs."""

    def __init__(self):
        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._keepalive_page: Optional[Page] = None
        self._pages: dict[str, Page] = {}
        self._status: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._running = False

    async def start(self):
        """Launch the ghost browser (headed, off-screen)."""
        os.makedirs(USER_DATA_DIR, exist_ok=True)

        self._playwright = await async_playwright().start()

        self._context = await self._playwright.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            args=[
                "--window-position=-2400,-2400",
                "--no-first-run",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-default-browser-check",
            ],
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=True,
            bypass_csp=True,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        if self._context.pages:
            self._keepalive_page = self._context.pages[0]
            await self._keepalive_page.goto("about:blank")
            for p in self._context.pages[1:]:
                await p.close()
        else:
            self._keepalive_page = await self._context.new_page()
            await self._keepalive_page.goto("about:blank")

        self._running = True
        print("🧬 OrganManager started (Playwright ghost browser)")

    async def stop(self):
        """Shut down the browser."""
        self._running = False
        self._keepalive_page = None
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._context = None
        self._playwright = None
        self._pages.clear()
        self._status.clear()
        print("🧬 OrganManager stopped")

    @property
    def is_running(self) -> bool:
        return self._running and self._context is not None

    async def _ensure_context(self):
        """Re-launch the browser if the context died."""
        if self._context is not None:
            try:
                if self._keepalive_page and not self._keepalive_page.is_closed():
                    return
            except Exception:
                pass
        print("🧬 OrganManager: context died, restarting browser...")
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._pages.clear()
        self._status.clear()
        await self.start()

    # ── Tab (organ) management ──────────────────────────────────

    async def open_organ(self, organ_id: str, url: str) -> dict:
        """Open a new tab for an organ. If already open, return existing."""
        if not self._running:
            return {"status": "error", "detail": "organ manager not started"}

        await self._ensure_context()

        async with self._lock:
            if organ_id in self._pages:
                page = self._pages[organ_id]
                if not page.is_closed():
                    return {
                        "status": "ok",
                        "action": "already_open",
                        "organ_id": organ_id,
                        "url": page.url,
                        "title": await page.title(),
                    }
                else:
                    del self._pages[organ_id]

            page = await self._context.new_page()
            self._pages[organ_id] = page
            self._status[organ_id] = {
                "status": "loading",
                "timestamp": datetime.utcnow().isoformat(),
                "url": url,
                "title": "",
            }

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            title = await page.title()
            self._status[organ_id] = {
                "status": "connected",
                "timestamp": datetime.utcnow().isoformat(),
                "url": page.url,
                "title": title,
            }
            print(f"🧬 Organ [{organ_id}] opened: {url} — {title}")
            return {
                "status": "ok",
                "action": "opened",
                "organ_id": organ_id,
                "url": page.url,
                "title": title,
            }
        except Exception as e:
            self._status[organ_id] = {
                "status": "error",
                "timestamp": datetime.utcnow().isoformat(),
                "url": url,
                "title": "",
                "error": str(e),
            }
            return {"status": "error", "detail": str(e)}

    async def close_organ(self, organ_id: str) -> dict:
        """Close an organ's tab."""
        async with self._lock:
            page = self._pages.pop(organ_id, None)
            self._status.pop(organ_id, None)

        if page and not page.is_closed():
            try:
                await page.close()
            except Exception:
                pass
            print(f"🧬 Organ [{organ_id}] closed")
            return {"status": "ok"}

        return {"status": "ok", "detail": "was not open"}

    async def get_open_organs(self) -> list[dict]:
        """Get all currently open organ tabs with their status."""
        result = []
        dead = []
        for organ_id, page in self._pages.items():
            if page.is_closed():
                dead.append(organ_id)
                continue
            info = self._status.get(organ_id, {})
            try:
                title = await page.title()
            except Exception:
                title = info.get("title", "")
            result.append({
                "organ_id": organ_id,
                "url": page.url,
                "title": title,
                "status": info.get("status", "unknown"),
                "timestamp": info.get("timestamp"),
            })
        for oid in dead:
            self._pages.pop(oid, None)
            self._status.pop(oid, None)
        return result

    def get_organ_status(self, organ_id: str) -> dict:
        """Get status of a specific organ."""
        if organ_id in self._pages and not self._pages[organ_id].is_closed():
            info = self._status.get(organ_id, {})
            return {
                "status": info.get("status", "connected"),
                "timestamp": info.get("timestamp"),
                "running": True,
                "url": info.get("url", ""),
            }
        return {"status": "closed", "running": False}

    def is_organ_open(self, organ_id: str) -> bool:
        """Check if an organ tab is open and alive."""
        page = self._pages.get(organ_id)
        return page is not None and not page.is_closed()

    # ── Pattern matching ────────────────────────────────────────

    async def match_pattern(self, organ_id: str, outer_html: str) -> dict:
        """Given an outer HTML snippet, fingerprint it and find all structurally
        similar elements in the organ's live page.

        Uses the NEW deep structural analysis: discovers inner fields and
        extracts structured objects from each match.

        Returns: {
            "fingerprint": { tag, classes, attrs },
            "fields": [ { label, css_path, extract, example }, ... ],
            "count": N,
            "matches": [ { user: "alice", repo: "...", __score: 42 }, ... ],
        }
        """
        page = self._pages.get(organ_id)
        if not page or page.is_closed():
            return {"error": "organ not open", "fingerprint": {}, "fields": [], "count": 0, "matches": []}

        analysis = discover_fields(outer_html)
        fp = analysis["fingerprint"]
        fields = analysis["fields"]

        if not fp.get("tag"):
            return {"error": "could not parse HTML snippet", "fingerprint": fp, "fields": [], "count": 0, "matches": []}

        js_code = build_deep_match_js(fp, fields)

        try:
            result = await page.evaluate(js_code)
            if isinstance(result, dict):
                return {
                    "fingerprint": fp,
                    "fields": fields,
                    "threshold": result.get("threshold", 0),
                    "expectedFields": result.get("expectedFields", len(fields)),
                    "duplicatesSkipped": result.get("duplicatesSkipped", 0),
                    "count": result.get("count", 0),
                    "matches": result.get("matches", []),
                }
            return {"fingerprint": fp, "fields": fields, "count": 0, "matches": [], "error": "unexpected result"}
        except Exception as e:
            return {"fingerprint": fp, "fields": fields, "count": 0, "matches": [], "error": str(e)}

    async def scrape_pattern(self, organ_id: str, outer_html: str) -> list:
        """Match pattern and return structured data from all matches."""
        result = await self.match_pattern(organ_id, outer_html)
        items = []
        for m in result.get("matches", []):
            # Filter out internal keys for storage
            item = {k: v for k, v in m.items() if not k.startswith('__')}
            if item:
                items.append(item)
            elif m.get("__text"):
                items.append(m["__text"])
        return items

    async def get_html(self, organ_id: str) -> dict:
        """Get full page HTML of an organ."""
        page = self._pages.get(organ_id)
        if not page or page.is_closed():
            return {"html": None, "error": "organ not open"}

        try:
            html = await page.content()
            return {"html": html, "url": page.url}
        except Exception as e:
            return {"html": None, "error": str(e)}


# ── Helpers ──────────────────────────────────────────────

def _css_escape(s: str) -> str:
    out = []
    for ch in s:
        if ch in ('.', ':', '[', ']', '(', ')', '#', '>', '+', '~', ',', ' ',
                  '!', '"', "'", '\\', '/', '{', '}', '=', '^', '$', '*', '|'):
            out.append('\\' + ch)
        else:
            out.append(ch)
    return ''.join(out)


def _js_string(s: str) -> str:
    escaped = s.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r')
    return "'" + escaped + "'"


def _js_array(items: list) -> str:
    parts = [_js_string(s) for s in items]
    return "[" + ", ".join(parts) + "]"


def _js_object(d: dict) -> str:
    parts = [f"{_js_string(k)}: {_js_string(v)}" for k, v in d.items()]
    return "{" + ", ".join(parts) + "}"
