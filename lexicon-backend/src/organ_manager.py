"""
Organ Manager — Playwright-based browser controller for Lexicon organs.

Architecture:
  A SINGLE headed Chromium browser runs off-screen (--window-position=-2400,-2400).
  Each organ is a TAB in that browser. The browser is persistent (cookies/sessions
  survive restarts via user_data_dir). The browser is "headed" (not headless) so
  sites like WhatsApp see a real browser — but it's positioned off-screen so it
  never appears on the user's desktop.

  Pattern Matching:
    The user pastes an outer HTML snippet from their browser and names it.
    We fingerprint the snippet (tag, classes, aria-labels, data-attributes, etc.)
    and build a similarity matcher that finds ALL structurally similar elements
    in the page. The text content of each match is extracted and stored under
    the given class name in Memory.

  This replaces DOM tree inspectors, variable mappers, and dashboards with
  a single, dead-simple workflow:
    1. Open a site as an organ tab
    2. Paste an outer HTML of an element you care about
    3. Name it (e.g. "contact", "message", "repo")
    4. All matching elements are scraped and stored

Usage:
  The OrganManager is started during Brain lifespan and exposes methods
  that the FastAPI endpoints call directly.
"""

import asyncio
import os
import re
from datetime import datetime
from typing import Optional
from html.parser import HTMLParser

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


# Where persistent browser data lives (cookies, localStorage, etc.)
USER_DATA_DIR = os.path.expanduser("~/.local/share/lexicon/organs/browser_data")


class _TagFingerprinter(HTMLParser):
    """Parse an outer HTML snippet and extract a structural fingerprint
    from the FIRST opening tag only (tag name, classes, key attributes)."""

    def __init__(self):
        super().__init__()
        self.tag = None
        self.classes = []
        self.attrs = {}
        self.done = False

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        self.tag = tag.lower()
        attr_dict = dict(attrs)
        # Extract classes
        cls = attr_dict.get("class", "")
        if cls:
            self.classes = [c.strip() for c in cls.split() if c.strip()]
        # Keep meaningful attributes for matching
        keep = [
            "role", "aria-label", "data-testid", "data-view-component",
            "data-hovercard-type", "type", "name", "data-tab",
            "aria-selected", "aria-expanded", "tabindex",
        ]
        for k in keep:
            if k in attr_dict and attr_dict[k]:
                self.attrs[k] = attr_dict[k]
        # Also keep any data- attributes (they tend to be structural)
        for k, v in attr_dict.items():
            if k.startswith("data-") and k not in ("data-hydro-click", "data-hydro-click-hmac",
                                                     "data-hovercard-url", "data-octo-click",
                                                     "data-octo-dimensions") and v:
                if len(v) < 100:  # skip huge data- blobs
                    self.attrs[k] = v
        self.done = True


def fingerprint_html(outer_html: str) -> dict:
    """Extract a structural fingerprint from an outer HTML snippet.

    Returns: {
        "tag": "a",
        "classes": ["Link--primary", "Link", "text-bold"],
        "attrs": {"data-view-component": "true", "data-hovercard-type": "user"},
    }
    """
    parser = _TagFingerprinter()
    try:
        parser.feed(outer_html)
    except Exception:
        pass

    if not parser.tag:
        return {"tag": "", "classes": [], "attrs": {}}

    return {
        "tag": parser.tag,
        "classes": parser.classes,
        "attrs": parser.attrs,
    }


def build_match_js(fingerprint: dict) -> str:
    """Build a JavaScript IIFE that finds all elements structurally
    similar to the given fingerprint using similarity scoring.

    Scoring:
      +10  matching tag
      +5   each matching class
      +8   each matching attribute key+value
      +3   each matching attribute key (different value)

    Elements above 35% of max possible score are returned.
    """
    tag = fingerprint.get("tag", "").lower()
    classes = fingerprint.get("classes", [])
    attrs = fingerprint.get("attrs", {})

    if not tag:
        return "(() => ({ error: 'no tag in fingerprint', matches: [] }))()"

    classes_json = _js_array(classes)
    attrs_json = _js_object(attrs)

    return f"""
    (() => {{
        const TAG = {_js_string(tag)};
        const CLASSES = {classes_json};
        const ATTRS = {attrs_json};

        const totalSignals = 10 + CLASSES.length * 5 + Object.keys(ATTRS).length * 8;
        const threshold = Math.max(10, totalSignals * 0.35);

        const candidates = document.querySelectorAll(TAG);
        const results = [];

        for (let i = 0; i < candidates.length && results.length < 200; i++) {{
            const el = candidates[i];
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

            if (score >= threshold) {{
                const text = (el.textContent || '').trim().substring(0, 500);
                let outerSnippet = '';
                try {{ outerSnippet = el.outerHTML.substring(0, 400); }} catch(_) {{}}
                results.push({{
                    text: text || null,
                    outerHtml: outerSnippet || null,
                    tag: el.tagName.toLowerCase(),
                    classes: elClasses.slice(0, 10),
                    score: score,
                }});
            }}
        }}

        results.sort((a, b) => b.score - a.score);

        return {{
            threshold: threshold,
            totalSignals: totalSignals,
            count: results.length,
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

        Returns: {
            "fingerprint": { tag, classes, attrs },
            "count": N,
            "matches": [ { text, outerHtml, tag, classes, score }, ... ],
        }
        """
        page = self._pages.get(organ_id)
        if not page or page.is_closed():
            return {"error": "organ not open", "fingerprint": {}, "count": 0, "matches": []}

        fp = fingerprint_html(outer_html)
        if not fp.get("tag"):
            return {"error": "could not parse HTML snippet", "fingerprint": fp, "count": 0, "matches": []}

        js_code = build_match_js(fp)

        try:
            result = await page.evaluate(js_code)
            if isinstance(result, dict):
                return {
                    "fingerprint": fp,
                    "threshold": result.get("threshold", 0),
                    "count": result.get("count", 0),
                    "matches": result.get("matches", []),
                }
            return {"fingerprint": fp, "count": 0, "matches": [], "error": "unexpected result"}
        except Exception as e:
            return {"fingerprint": fp, "count": 0, "matches": [], "error": str(e)}

    async def scrape_pattern(self, organ_id: str, outer_html: str) -> list[str]:
        """Match pattern and return just the text content of all matches."""
        result = await self.match_pattern(organ_id, outer_html)
        texts = []
        for m in result.get("matches", []):
            t = (m.get("text") or "").strip()
            if t:
                texts.append(t)
        return texts

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
