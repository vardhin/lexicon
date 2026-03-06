"""
Automation Engine — Programmable browser automation for Lexicon organs.

Goes beyond static scraping: dynamically crawl through Playwright tabs
by executing action sequences (click, scroll, navigate, wait, type,
paginate, extract) to discover and fetch data across multiple pages.

Architecture:
  An automation is a named sequence of STEPS. Each step is an action
  (click a link, scroll down, wait for a selector, type into an input,
  extract data, etc.). Steps run in order against an organ's live
  Playwright page. Automations can be saved to Memory and re-run.

  Automations are organ-scoped — each automation belongs to an organ
  and runs against that organ's open Playwright tab.

Step Types:
  - click        → Click an element by CSS selector
  - type         → Type text into an input field
  - scroll       → Scroll the page or an element
  - wait         → Wait for a selector to appear or a fixed delay
  - navigate     → Go to a URL (absolute or relative)
  - extract      → Run a scrape pattern (reuse existing fingerprint/field logic)
  - paginate     → Click through pages, extracting on each
  - screenshot   → Capture a screenshot (useful for debugging)
  - eval_js      → Evaluate arbitrary JavaScript in the page context
  - conditional  → Run sub-steps only if a selector exists
  - loop         → Repeat sub-steps N times or until a condition

Usage:
  POST /organs/{organ_id}/automations          → Create/save an automation
  GET  /organs/{organ_id}/automations          → List saved automations
  POST /organs/{organ_id}/automations/{name}/run → Execute an automation
  DELETE /organs/{organ_id}/automations/{name}  → Delete an automation
  POST /organs/{organ_id}/actions/click         → One-shot: click
  POST /organs/{organ_id}/actions/type          → One-shot: type
  POST /organs/{organ_id}/actions/scroll        → One-shot: scroll
  POST /organs/{organ_id}/actions/navigate      → One-shot: navigate
  POST /organs/{organ_id}/actions/screenshot    → One-shot: screenshot
  POST /organs/{organ_id}/actions/eval          → One-shot: eval JS
  POST /organs/{organ_id}/actions/extract       → One-shot: extract with pattern
  POST /organs/{organ_id}/actions/paginate      → One-shot: paginate + extract
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP DEFINITIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VALID_STEP_TYPES = {
    "click", "type", "scroll", "wait", "navigate", "extract",
    "paginate", "screenshot", "eval_js", "conditional", "loop",
}


@dataclass
class StepResult:
    """Result of executing a single automation step."""
    step_index: int
    step_type: str
    success: bool
    duration_ms: float
    data: Any = None          # Extracted data, screenshot base64, eval result, etc.
    error: Optional[str] = None
    skipped: bool = False     # True if conditional was false


@dataclass
class AutomationResult:
    """Result of executing a full automation."""
    automation_name: str
    organ_id: str
    success: bool
    total_steps: int
    completed_steps: int
    duration_ms: float
    step_results: list[StepResult] = field(default_factory=list)
    extracted_data: list[dict] = field(default_factory=list)   # All data from extract steps
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "automation_name": self.automation_name,
            "organ_id": self.organ_id,
            "success": self.success,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "duration_ms": round(self.duration_ms, 1),
            "extracted_data": self.extracted_data,
            "error": self.error,
            "steps": [
                {
                    "index": r.step_index,
                    "type": r.step_type,
                    "success": r.success,
                    "duration_ms": round(r.duration_ms, 1),
                    "data_count": len(r.data) if isinstance(r.data, list) else (1 if r.data else 0),
                    "error": r.error,
                    "skipped": r.skipped,
                }
                for r in self.step_results
            ],
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  AUTOMATION EXECUTOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AutomationExecutor:
    """Executes automation steps against a Playwright page."""

    def __init__(self, organ_manager, memory):
        self._organs = organ_manager
        self._memory = memory

    async def execute(self, organ_id: str, automation_name: str,
                      steps: list[dict],
                      broadcast_fn=None) -> AutomationResult:
        """Execute a sequence of automation steps against an organ's page.

        Args:
            organ_id: The organ whose tab to automate
            automation_name: Name for logging/results
            steps: List of step dicts, each with "type" and type-specific params
            broadcast_fn: Optional async callable to push progress updates
        """
        start = time.monotonic()
        page = self._organs._pages.get(organ_id)

        if not page or page.is_closed():
            return AutomationResult(
                automation_name=automation_name,
                organ_id=organ_id,
                success=False,
                total_steps=len(steps),
                completed_steps=0,
                duration_ms=0,
                error="organ not open",
            )

        result = AutomationResult(
            automation_name=automation_name,
            organ_id=organ_id,
            success=True,
            total_steps=len(steps),
            completed_steps=0,
            duration_ms=0,
        )

        for i, step in enumerate(steps):
            step_type = step.get("type", "").lower()
            if step_type not in VALID_STEP_TYPES:
                sr = StepResult(i, step_type, False, 0, error=f"unknown step type: {step_type}")
                result.step_results.append(sr)
                result.success = False
                result.error = sr.error
                break

            # Broadcast progress
            if broadcast_fn:
                try:
                    await broadcast_fn({
                        "type": "AUTOMATION_PROGRESS",
                        "organ_id": organ_id,
                        "automation": automation_name,
                        "step": i + 1,
                        "total": len(steps),
                        "step_type": step_type,
                    })
                except Exception:
                    pass

            sr = await self._execute_step(page, i, step, organ_id)
            result.step_results.append(sr)
            result.completed_steps = i + 1

            # Collect extracted data
            if sr.success and step_type in ("extract", "paginate") and isinstance(sr.data, list):
                result.extracted_data.extend(sr.data)

            if not sr.success and not sr.skipped:
                # Check if step has continue_on_error flag
                if not step.get("continue_on_error", False):
                    result.success = False
                    result.error = f"step {i} ({step_type}) failed: {sr.error}"
                    break

        result.duration_ms = (time.monotonic() - start) * 1000

        # Store extracted data in Memory if any
        if result.extracted_data:
            class_name = f"auto_{automation_name}"
            await self._memory.store_scraped_data(organ_id, class_name, result.extracted_data)

        return result

    async def _execute_step(self, page: Page, index: int,
                            step: dict, organ_id: str) -> StepResult:
        """Execute a single step. Dispatches by type."""
        step_type = step.get("type", "").lower()
        start = time.monotonic()

        try:
            if step_type == "click":
                data = await self._step_click(page, step)
            elif step_type == "type":
                data = await self._step_type(page, step)
            elif step_type == "scroll":
                data = await self._step_scroll(page, step)
            elif step_type == "wait":
                data = await self._step_wait(page, step)
            elif step_type == "navigate":
                data = await self._step_navigate(page, step)
            elif step_type == "extract":
                data = await self._step_extract(page, step, organ_id)
            elif step_type == "paginate":
                data = await self._step_paginate(page, step, organ_id)
            elif step_type == "screenshot":
                data = await self._step_screenshot(page, step)
            elif step_type == "eval_js":
                data = await self._step_eval(page, step)
            elif step_type == "conditional":
                data = await self._step_conditional(page, step, index, organ_id)
            elif step_type == "loop":
                data = await self._step_loop(page, step, index, organ_id)
            else:
                return StepResult(index, step_type, False, 0,
                                  error=f"unknown type: {step_type}")

            elapsed = (time.monotonic() - start) * 1000
            return StepResult(index, step_type, True, elapsed, data=data)

        except PlaywrightTimeout as e:
            elapsed = (time.monotonic() - start) * 1000
            return StepResult(index, step_type, False, elapsed,
                              error=f"timeout: {e}")
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return StepResult(index, step_type, False, elapsed,
                              error=str(e))

    # ── Individual step implementations ─────────────────────

    async def _step_click(self, page: Page, step: dict) -> dict:
        """Click an element.

        Params:
            selector: CSS selector of element to click
            timeout: ms to wait for element (default 5000)
            button: "left" | "right" | "middle" (default "left")
            count: number of clicks (default 1, use 2 for double-click)
            wait_after: ms to wait after clicking (default 500)
        """
        selector = step.get("selector", "")
        timeout = step.get("timeout", 5000)
        button = step.get("button", "left")
        count = step.get("count", 1)
        wait_after = step.get("wait_after", 500)

        if not selector:
            raise ValueError("click: 'selector' is required")

        await page.wait_for_selector(selector, timeout=timeout)
        await page.click(selector, button=button, click_count=count)

        if wait_after > 0:
            await asyncio.sleep(wait_after / 1000)

        return {"clicked": selector, "button": button, "count": count}

    async def _step_type(self, page: Page, step: dict) -> dict:
        """Type text into an input element.

        Params:
            selector: CSS selector of input element
            text: text to type
            clear: whether to clear existing value first (default True)
            press_enter: whether to press Enter after typing (default False)
            delay: ms delay between keystrokes (default 50)
            timeout: ms to wait for element (default 5000)
        """
        selector = step.get("selector", "")
        text = step.get("text", "")
        clear = step.get("clear", True)
        press_enter = step.get("press_enter", False)
        delay = step.get("delay", 50)
        timeout = step.get("timeout", 5000)

        if not selector:
            raise ValueError("type: 'selector' is required")

        await page.wait_for_selector(selector, timeout=timeout)

        if clear:
            await page.fill(selector, "")

        await page.type(selector, text, delay=delay)

        if press_enter:
            await page.press(selector, "Enter")
            await asyncio.sleep(0.5)

        return {"typed": text, "into": selector, "pressed_enter": press_enter}

    async def _step_scroll(self, page: Page, step: dict) -> dict:
        """Scroll the page or a specific element.

        Params:
            direction: "down" | "up" | "bottom" | "top" (default "down")
            amount: pixels to scroll (default 800, ignored for bottom/top)
            selector: CSS selector of scrollable container (default: page)
            wait_after: ms to wait after scrolling (default 1000)
            smooth: whether to use smooth scrolling (default True)
        """
        direction = step.get("direction", "down")
        amount = step.get("amount", 800)
        selector = step.get("selector", None)
        wait_after = step.get("wait_after", 1000)

        if selector:
            # Scroll within a specific element
            if direction == "bottom":
                js = f"document.querySelector('{selector}').scrollTop = document.querySelector('{selector}').scrollHeight"
            elif direction == "top":
                js = f"document.querySelector('{selector}').scrollTop = 0"
            elif direction == "up":
                js = f"document.querySelector('{selector}').scrollBy(0, -{amount})"
            else:
                js = f"document.querySelector('{selector}').scrollBy(0, {amount})"
        else:
            # Scroll the whole page
            if direction == "bottom":
                js = "window.scrollTo(0, document.body.scrollHeight)"
            elif direction == "top":
                js = "window.scrollTo(0, 0)"
            elif direction == "up":
                js = f"window.scrollBy(0, -{amount})"
            else:
                js = f"window.scrollBy(0, {amount})"

        await page.evaluate(js)

        if wait_after > 0:
            await asyncio.sleep(wait_after / 1000)

        return {"scrolled": direction, "amount": amount, "selector": selector}

    async def _step_wait(self, page: Page, step: dict) -> dict:
        """Wait for a condition.

        Params:
            selector: CSS selector to wait for (optional)
            state: "visible" | "hidden" | "attached" | "detached" (default "visible")
            delay: fixed delay in ms (used if no selector, default 0)
            timeout: ms to wait for selector (default 10000)
        """
        selector = step.get("selector", None)
        state = step.get("state", "visible")
        delay = step.get("delay", 0)
        timeout = step.get("timeout", 10000)

        if selector:
            await page.wait_for_selector(selector, state=state, timeout=timeout)
            return {"waited_for": selector, "state": state}
        elif delay > 0:
            await asyncio.sleep(delay / 1000)
            return {"waited_ms": delay}
        else:
            # Wait for network idle
            await page.wait_for_load_state("networkidle", timeout=timeout)
            return {"waited_for": "networkidle"}

    async def _step_navigate(self, page: Page, step: dict) -> dict:
        """Navigate to a URL.

        Params:
            url: URL to navigate to (absolute or relative)
            wait_until: "load" | "domcontentloaded" | "networkidle" (default "domcontentloaded")
            timeout: ms timeout (default 30000)
        """
        url = step.get("url", "")
        wait_until = step.get("wait_until", "domcontentloaded")
        timeout = step.get("timeout", 30000)

        if not url:
            raise ValueError("navigate: 'url' is required")

        # Handle relative URLs
        if url.startswith("/"):
            current = page.url
            from urllib.parse import urlparse
            parsed = urlparse(current)
            url = f"{parsed.scheme}://{parsed.netloc}{url}"

        await page.goto(url, wait_until=wait_until, timeout=timeout)
        title = await page.title()

        return {"navigated_to": page.url, "title": title}

    async def _step_extract(self, page: Page, step: dict,
                            organ_id: str) -> list:
        """Extract structured data using the organ's scrape engine.

        Params:
            outer_html: HTML pattern to match (uses the organ's deep match engine)
            class_name: name for this data class (optional, for storage)
            OR
            selector: CSS selector — extract text/attributes from all matches
            attribute: attribute to extract (default "textContent")
            limit: max items to extract (default 100)
        """
        outer_html = step.get("outer_html", "")

        if outer_html:
            # Use the organ's full structural scraping engine
            result = await self._organs.match_pattern(organ_id, outer_html)
            values = []
            for m in result.get("matches", []):
                item = {k: v for k, v in m.items() if not k.startswith("__") and v}
                if item:
                    values.append(item)
            return values
        else:
            # Simple CSS selector extraction
            selector = step.get("selector", "")
            attribute = step.get("attribute", "textContent")
            limit = step.get("limit", 100)

            if not selector:
                raise ValueError("extract: 'outer_html' or 'selector' required")

            js = f"""
            (() => {{
                const els = document.querySelectorAll('{selector}');
                const results = [];
                for (let i = 0; i < Math.min(els.length, {limit}); i++) {{
                    const el = els[i];
                    const item = {{}};
                    if ('{attribute}' === 'textContent') {{
                        item.text = (el.textContent || '').trim().substring(0, 500);
                    }} else if ('{attribute}' === 'innerHTML') {{
                        item.html = el.innerHTML.substring(0, 2000);
                    }} else {{
                        item.value = el.getAttribute('{attribute}') || '';
                    }}
                    if (Object.values(item).some(v => v)) results.push(item);
                }}
                return results;
            }})()
            """
            return await page.evaluate(js)

    async def _step_paginate(self, page: Page, step: dict,
                             organ_id: str) -> list:
        """Click through pages, extracting data on each page.

        Params:
            next_selector: CSS selector for the "next page" button/link
            extract: extraction config (same as extract step params)
            max_pages: maximum number of pages to crawl (default 5)
            wait_between: ms to wait between page loads (default 2000)
            stop_if_empty: stop if no data extracted on a page (default True)
        """
        next_selector = step.get("next_selector", "")
        extract_config = step.get("extract", {})
        max_pages = step.get("max_pages", 5)
        wait_between = step.get("wait_between", 2000)
        stop_if_empty = step.get("stop_if_empty", True)

        if not next_selector:
            raise ValueError("paginate: 'next_selector' is required")
        if not extract_config:
            raise ValueError("paginate: 'extract' config is required")

        all_data = []

        for page_num in range(max_pages):
            # Extract data from current page
            extract_step = {**extract_config, "type": "extract"}
            page_data = await self._step_extract(page, extract_step, organ_id)

            if isinstance(page_data, list):
                all_data.extend(page_data)

            if stop_if_empty and not page_data:
                break

            # Check if next button exists and is enabled
            next_exists = await page.evaluate(f"""
                (() => {{
                    const el = document.querySelector('{next_selector}');
                    if (!el) return false;
                    if (el.disabled) return false;
                    if (el.classList.contains('disabled')) return false;
                    if (el.getAttribute('aria-disabled') === 'true') return false;
                    return true;
                }})()
            """)

            if not next_exists:
                break

            # Click next
            await page.click(next_selector)
            await asyncio.sleep(wait_between / 1000)

            # Wait for page to settle
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeout:
                pass  # Some SPAs never reach networkidle

        return all_data

    async def _step_screenshot(self, page: Page, step: dict) -> dict:
        """Capture a screenshot.

        Params:
            full_page: whether to capture full scrollable page (default False)
            selector: capture only this element (optional)
            quality: JPEG quality 0-100 (default 80)
        """
        full_page = step.get("full_page", False)
        selector = step.get("selector", None)
        quality = step.get("quality", 80)

        if selector:
            element = await page.query_selector(selector)
            if element:
                img_bytes = await element.screenshot(type="jpeg", quality=quality)
            else:
                raise ValueError(f"screenshot: selector '{selector}' not found")
        else:
            img_bytes = await page.screenshot(type="jpeg", quality=quality,
                                               full_page=full_page)

        b64 = base64.b64encode(img_bytes).decode("ascii")
        return {"screenshot": b64, "size": len(img_bytes)}

    async def _step_eval(self, page: Page, step: dict) -> Any:
        """Evaluate JavaScript in the page context.

        Params:
            js: JavaScript code to evaluate (must return a value)
            timeout: ms timeout (default 10000)
        """
        js = step.get("js", "")
        if not js:
            raise ValueError("eval_js: 'js' is required")

        result = await page.evaluate(js)
        return result

    async def _step_conditional(self, page: Page, step: dict,
                                parent_index: int, organ_id: str) -> Any:
        """Run sub-steps only if a selector exists.

        Params:
            selector: CSS selector to check for existence
            then: list of steps to run if selector exists
            otherwise: list of steps to run if selector doesn't exist (optional)
        """
        selector = step.get("selector", "")
        then_steps = step.get("then", [])
        otherwise_steps = step.get("otherwise", [])

        if not selector:
            raise ValueError("conditional: 'selector' is required")

        exists = await page.evaluate(
            f"!!document.querySelector('{selector}')"
        )

        sub_steps = then_steps if exists else otherwise_steps
        if not sub_steps:
            return {"condition": exists, "executed": 0}

        results = []
        for j, sub_step in enumerate(sub_steps):
            sr = await self._execute_step(page, parent_index * 100 + j,
                                          sub_step, organ_id)
            results.append(sr)
            if not sr.success and not sub_step.get("continue_on_error", False):
                break

        # Collect any extracted data from sub-steps
        extracted = []
        for sr in results:
            if sr.success and isinstance(sr.data, list):
                extracted.extend(sr.data)

        return extracted if extracted else {"condition": exists, "executed": len(results)}

    async def _step_loop(self, page: Page, step: dict,
                         parent_index: int, organ_id: str) -> list:
        """Repeat sub-steps N times or until a stop condition.

        Params:
            count: number of iterations (default 3)
            steps: list of steps to repeat each iteration
            stop_selector: if this selector appears, stop looping (optional)
            stop_if_no_change: stop if page content hash doesn't change (default True)
        """
        count = step.get("count", 3)
        sub_steps = step.get("steps", [])
        stop_selector = step.get("stop_selector", None)
        stop_if_no_change = step.get("stop_if_no_change", True)

        if not sub_steps:
            raise ValueError("loop: 'steps' is required")

        all_data = []
        prev_hash = None

        for iteration in range(count):
            # Check stop condition
            if stop_selector:
                exists = await page.evaluate(
                    f"!!document.querySelector('{stop_selector}')"
                )
                if exists:
                    break

            # Check for content change
            if stop_if_no_change and iteration > 0:
                current_hash = await page.evaluate(
                    "document.body.innerText.length.toString() + '-' + document.body.scrollHeight.toString()"
                )
                if current_hash == prev_hash:
                    break
                prev_hash = current_hash
            elif stop_if_no_change:
                prev_hash = await page.evaluate(
                    "document.body.innerText.length.toString() + '-' + document.body.scrollHeight.toString()"
                )

            for j, sub_step in enumerate(sub_steps):
                sr = await self._execute_step(
                    page, parent_index * 1000 + iteration * 100 + j,
                    sub_step, organ_id
                )
                if sr.success and isinstance(sr.data, list):
                    all_data.extend(sr.data)
                if not sr.success and not sub_step.get("continue_on_error", False):
                    return all_data

        return all_data

    # ── One-shot actions (no automation sequence needed) ──

    async def action_click(self, organ_id: str, selector: str,
                           **kwargs) -> StepResult:
        """One-shot click action."""
        page = self._organs._pages.get(organ_id)
        if not page or page.is_closed():
            return StepResult(0, "click", False, 0, error="organ not open")
        step = {"type": "click", "selector": selector, **kwargs}
        return await self._execute_step(page, 0, step, organ_id)

    async def action_type(self, organ_id: str, selector: str,
                          text: str, **kwargs) -> StepResult:
        """One-shot type action."""
        page = self._organs._pages.get(organ_id)
        if not page or page.is_closed():
            return StepResult(0, "type", False, 0, error="organ not open")
        step = {"type": "type", "selector": selector, "text": text, **kwargs}
        return await self._execute_step(page, 0, step, organ_id)

    async def action_scroll(self, organ_id: str, **kwargs) -> StepResult:
        """One-shot scroll action."""
        page = self._organs._pages.get(organ_id)
        if not page or page.is_closed():
            return StepResult(0, "scroll", False, 0, error="organ not open")
        step = {"type": "scroll", **kwargs}
        return await self._execute_step(page, 0, step, organ_id)

    async def action_navigate(self, organ_id: str, url: str,
                              **kwargs) -> StepResult:
        """One-shot navigate action."""
        page = self._organs._pages.get(organ_id)
        if not page or page.is_closed():
            return StepResult(0, "navigate", False, 0, error="organ not open")
        step = {"type": "navigate", "url": url, **kwargs}
        return await self._execute_step(page, 0, step, organ_id)

    async def action_screenshot(self, organ_id: str, **kwargs) -> StepResult:
        """One-shot screenshot action."""
        page = self._organs._pages.get(organ_id)
        if not page or page.is_closed():
            return StepResult(0, "screenshot", False, 0, error="organ not open")
        step = {"type": "screenshot", **kwargs}
        return await self._execute_step(page, 0, step, organ_id)

    async def action_eval(self, organ_id: str, js: str, **kwargs) -> StepResult:
        """One-shot JavaScript eval action."""
        page = self._organs._pages.get(organ_id)
        if not page or page.is_closed():
            return StepResult(0, "eval_js", False, 0, error="organ not open")
        step = {"type": "eval_js", "js": js, **kwargs}
        return await self._execute_step(page, 0, step, organ_id)

    async def action_extract(self, organ_id: str, **kwargs) -> StepResult:
        """One-shot extract action."""
        page = self._organs._pages.get(organ_id)
        if not page or page.is_closed():
            return StepResult(0, "extract", False, 0, error="organ not open")
        step = {"type": "extract", **kwargs}
        return await self._execute_step(page, 0, step, organ_id)

    async def action_paginate(self, organ_id: str, **kwargs) -> StepResult:
        """One-shot paginate action."""
        page = self._organs._pages.get(organ_id)
        if not page or page.is_closed():
            return StepResult(0, "paginate", False, 0, error="organ not open")
        step = {"type": "paginate", **kwargs}
        return await self._execute_step(page, 0, step, organ_id)
