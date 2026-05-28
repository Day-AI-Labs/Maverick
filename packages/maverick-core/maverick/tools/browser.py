"""Browser tool. Playwright-driven web browsing as discrete actions.

Lets the agent navigate URLs, click links, fill forms, extract text,
and screenshot pages — discretely, action by action, with each action
visible in the trajectory.

Different from the ``computer`` tool: this is HIGH-LEVEL web automation
(navigate, find element by selector or text, click, fill). The computer
tool is low-level (click at pixel coords). Use browser for web tasks
that can be described semantically ("click the Login button"), and
computer for tasks where the UI isn't a normal DOM (desktop apps,
canvas-based interfaces, anti-bot challenges).

Persistent browser context across actions: the tool keeps a single
chromium instance alive in a module-level handle. Closed at the end
of the goal via ``close_browser()``.

Session persistence: cookies + localStorage are saved to disk
(``~/.maverick/browser/state.json`` by default, mode 0600) after each
navigation, on the ``save_session`` action, and at interpreter exit,
then reloaded when the next context starts -- so logins survive
restarts and crashes. Override the path with ``MAVERICK_BROWSER_STATE``
(per-task profiles) or disable with ``MAVERICK_BROWSER_NO_PERSIST=1``.

Safety:
  - All navigations are allow-listed by default to ``http(s)://`` URLs.
  - ``MAVERICK_BROWSER_DISABLE=1`` env var disables the tool entirely.
  - Each call is logged with action + URL for audit trail.
"""
from __future__ import annotations

import atexit
import base64
import ipaddress
import logging
import os
import re
from urllib.parse import urlparse
import threading
from pathlib import Path
from typing import Any, Optional

from . import Tool

log = logging.getLogger(__name__)


# ---------- session persistence (cookies + localStorage survive restarts) ----------

_DEFAULT_STATE_PATH = Path.home() / ".maverick" / "browser" / "state.json"


def _persist_enabled() -> bool:
    """On by default; opt out with MAVERICK_BROWSER_NO_PERSIST=1."""
    return os.environ.get("MAVERICK_BROWSER_NO_PERSIST") != "1"


def _state_path() -> Path:
    override = os.environ.get("MAVERICK_BROWSER_STATE")
    return Path(os.path.expanduser(override)) if override else _DEFAULT_STATE_PATH


def _restore_state_arg() -> Optional[str]:
    """storage_state path to seed a new context with, or None for a fresh one."""
    if not _persist_enabled():
        return None
    p = _state_path()
    return str(p) if p.exists() else None


_BROWSER_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "navigate", "click", "type", "fill_form", "press", "scroll",
                "screenshot", "extract_text", "extract_html",
                "find_text", "wait_for", "go_back", "go_forward",
                "current_url", "list_links", "save_session", "close",
            ],
            "description": "Action to perform.",
        },
        "url": {
            "type": "string",
            "description": "URL for 'navigate' (http/https only).",
        },
        "selector": {
            "type": "string",
            "description": "CSS selector or Playwright text= locator for click/type/find_text/wait_for.",
        },
        "text": {
            "type": "string",
            "description": "Text to type, key to press, or text to find.",
        },
        "fields": {
            "type": "object",
            "description": "For 'fill_form': a {css_selector: value} map; fills many inputs in one call, in order.",
            "additionalProperties": {"type": "string"},
        },
        "delta_y": {
            "type": "integer",
            "description": "Pixels to scroll vertically (positive = down).",
        },
        "timeout_ms": {
            "type": "integer",
            "description": "Override the default 30s action timeout.",
        },
    },
    "required": ["action"],
}


class _BrowserSession:
    """One persistent chromium instance, lazily started, thread-safe."""

    def __init__(self):
        self._lock = threading.Lock()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _ensure_started(self):
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise ImportError(
                "playwright not installed. Run: pip install 'maverick-agent[browser]' "
                "&& playwright install chromium"
            ) from e
        self._playwright = sync_playwright().start()
        headless = os.environ.get("MAVERICK_BROWSER_HEADED", "0") != "1"
        self._browser = self._playwright.chromium.launch(headless=headless)
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            storage_state=_restore_state_arg(),
        )
        self._page = self._context.new_page()

    @property
    def page(self):
        self._ensure_started()
        return self._page

    def save_state(self) -> bool:
        """Persist cookies + localStorage to disk. Returns True if written."""
        with self._lock:
            if self._context is None or not _persist_enabled():
                return False
            p = _state_path()
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                self._context.storage_state(path=str(p))
                try:
                    os.chmod(p, 0o600)  # cookies are sensitive
                except OSError:
                    pass
                return True
            except Exception as e:
                log.warning("browser save_state: %s", e)
                return False

    def close(self):
        with self._lock:
            for closer in (self._context, self._browser, self._playwright):
                if closer is None:
                    continue
                try:
                    if closer is self._playwright:
                        closer.stop()
                    else:
                        closer.close()
                except Exception as e:
                    log.warning("browser close: %s: %s", type(closer).__name__, e)
            self._page = self._context = self._browser = self._playwright = None


_session: Optional[_BrowserSession] = None
_session_lock = threading.Lock()


def _get_session() -> _BrowserSession:
    global _session
    with _session_lock:
        if _session is None:
            _session = _BrowserSession()
        return _session


def close_browser() -> None:
    """Tear down the persistent browser session. Idempotent."""
    global _session
    with _session_lock:
        if _session is not None:
            _session.save_state()
            _session.close()
            _session = None


def _save_on_exit() -> None:
    s = _session
    if s is not None:
        try:
            s.save_state()
        except Exception:
            pass


atexit.register(_save_on_exit)


_SAFE_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _is_safe_browser_url(url: str) -> bool:
    if not _SAFE_URL_RE.match(url):
        return False

    host = (urlparse(url).hostname or "").strip().lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return False

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Non-IP hostnames are allowed.
        return True

    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _run_browser_action(args: dict[str, Any]) -> str:
    if os.environ.get("MAVERICK_BROWSER_DISABLE") == "1":
        return "ERROR: browser tool disabled by MAVERICK_BROWSER_DISABLE=1"
    action = args.get("action")
    if not action:
        return "ERROR: action is required"

    if action == "close":
        close_browser()
        return "browser closed"

    try:
        session = _get_session()
        page = session.page
    except ImportError as e:
        return f"ERROR: {e}"

    timeout = int(args.get("timeout_ms") or 30_000)

    if action == "navigate":
        url = args.get("url") or ""
        if not _is_safe_browser_url(url):
            return (
                "ERROR: URL must be http(s) and must not target localhost or "
                f"non-public IP ranges; got {url!r}"
            )
        log.info("browser.navigate %s", url)
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        session.save_state()  # checkpoint cookies after each navigation
        return f"navigated to {page.url} (status: loaded)"

    if action == "current_url":
        return page.url

    if action == "go_back":
        page.go_back(timeout=timeout)
        return f"back -> {page.url}"

    if action == "go_forward":
        page.go_forward(timeout=timeout)
        return f"forward -> {page.url}"

    if action == "click":
        selector = args.get("selector")
        if not selector:
            return "ERROR: click requires selector"
        log.info("browser.click %s", selector)
        page.click(selector, timeout=timeout)
        return f"clicked {selector!r} on {page.url}"

    if action == "type":
        selector = args.get("selector")
        text = args.get("text") or ""
        if not selector:
            return "ERROR: type requires selector"
        log.info("browser.type len=%d into %s", len(text), selector)
        page.fill(selector, text, timeout=timeout)
        return f"typed {len(text)} chars into {selector!r}"

    if action == "fill_form":
        fields = args.get("fields")
        if not isinstance(fields, dict) or not fields:
            return "ERROR: fill_form requires a non-empty 'fields' object {selector: value}"
        filled: list[str] = []
        errors: list[str] = []
        for selector, value in fields.items():
            try:
                page.fill(selector, str(value), timeout=timeout)
                filled.append(selector)
            except Exception as e:
                errors.append(f"{selector}: {type(e).__name__}")
        log.info("browser.fill_form filled=%d errors=%d", len(filled), len(errors))
        summary = f"filled {len(filled)}/{len(fields)} field(s)"
        if errors:
            summary += "; failed: " + ", ".join(errors[:10])
        return summary

    if action == "press":
        text = args.get("text") or ""
        selector = args.get("selector")
        if not text:
            return "ERROR: press requires text (key name, e.g. 'Enter')"
        if selector:
            page.press(selector, text, timeout=timeout)
        else:
            page.keyboard.press(text)
        return f"pressed {text!r}"

    if action == "scroll":
        dy = int(args.get("delta_y") or 400)
        page.evaluate(f"window.scrollBy(0, {dy})")
        return f"scrolled by {dy}"

    if action == "screenshot":
        png_bytes = page.screenshot(full_page=False)
        b64 = base64.b64encode(png_bytes).decode("ascii")
        log.info("browser.screenshot len=%d url=%s", len(b64), page.url)
        return f"<screenshot mime=image/png base64>{b64}</screenshot>"

    if action == "extract_text":
        selector = args.get("selector")
        if selector:
            els = page.query_selector_all(selector)
            return "\n".join((el.inner_text() or "").strip() for el in els)[:50_000]
        # Whole-page text fallback.
        body = page.query_selector("body")
        if not body:
            return ""
        return (body.inner_text() or "").strip()[:50_000]

    if action == "extract_html":
        selector = args.get("selector")
        if selector:
            el = page.query_selector(selector)
            return (el.inner_html() if el else "")[:100_000]
        return page.content()[:100_000]

    if action == "find_text":
        text = args.get("text") or ""
        if not text:
            return "ERROR: find_text requires text"
        loc = page.get_by_text(text, exact=False)
        count = loc.count()
        if count == 0:
            return f"text {text!r} not found on {page.url}"
        # Return location summary for the first match.
        try:
            box = loc.first.bounding_box()
            if box:
                return (
                    f"found {count} match(es); first at "
                    f"({box['x']:.0f}, {box['y']:.0f}, "
                    f"{box['width']:.0f}x{box['height']:.0f})"
                )
        except Exception:
            pass
        return f"found {count} match(es) for {text!r}"

    if action == "wait_for":
        selector = args.get("selector")
        if not selector:
            return "ERROR: wait_for requires selector"
        page.wait_for_selector(selector, timeout=timeout)
        return f"selector {selector!r} appeared"

    if action == "list_links":
        anchors = page.query_selector_all("a[href]")
        links = []
        for a in anchors[:100]:
            href = a.get_attribute("href") or ""
            text = (a.inner_text() or "").strip()[:80]
            links.append(f"{text!r} -> {href}")
        return "\n".join(links) if links else "no links on page"

    if action == "save_session":
        ok = session.save_state()
        return "session saved" if ok else "session not saved (persistence disabled or no active context)"

    return f"ERROR: unknown action {action!r}"


def browser() -> Tool:
    """Factory: builds the browser tool."""
    return Tool(
        name="browser",
        description=(
            "Browse the web. navigate to a URL, find_text or use CSS selectors "
            "to interact (click, type, fill_form to batch-fill many inputs), "
            "extract_text or extract_html to read, "
            "screenshot to see, list_links to discover navigation. Use this "
            "for normal web tasks; use the 'computer' tool for non-DOM UIs."
        ),
        input_schema=_BROWSER_INPUT_SCHEMA,
        fn=_run_browser_action,
    )
