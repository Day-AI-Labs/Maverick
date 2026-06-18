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

Session persistence: cookies + localStorage are saved to disk only when
``MAVERICK_BROWSER_STATE`` explicitly points at a per-task profile file.
When enabled, the state file is mode 0600, checkpointed after navigation,
on the ``save_session`` action, and at interpreter exit, then reloaded
when the next context starts. Disable with ``MAVERICK_BROWSER_NO_PERSIST=1``.

Safety:
  - All navigations are allow-listed by default to ``http(s)://`` URLs.
  - ``MAVERICK_BROWSER_DISABLE=1`` env var disables the tool entirely.
  - Each call is logged with action + URL for audit trail.
"""
from __future__ import annotations

import atexit
import base64
import json
import logging
import os
import re
import threading
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..safety.action_evidence import seal_bracketed
from ..safety.action_gate import browser_action_risk, gate_browser_action
from . import Tool
from .http_fetch import _scan_fetched

log = logging.getLogger(__name__)


_MAX_FILL_FORM_FIELDS = 25
_MAX_FILL_FORM_SELECTOR_LENGTH = 500
_MAX_FILL_FORM_VALUE_LENGTH = 10_000
_MAX_FILL_FORM_FIELD_TIMEOUT_MS = 1_000
_MAX_FILL_FORM_TOTAL_TIMEOUT_MS = 5_000

# Bounds for the read-only ``observe`` snapshot so it never floods the context.
_MAX_OBSERVE_ELEMENTS = 100
_MAX_OBSERVE_NAME_LENGTH = 120
_MAX_OBSERVE_AXTREE_CHARS = 20_000


# ---------- session persistence (cookies + localStorage survive restarts) ----------

_DEFAULT_STATE_PATH = Path.home() / ".maverick" / "browser" / "state.json"


def _persist_enabled() -> bool:
    """Persistence is opt-in via an explicit per-task state file."""
    return (
        os.environ.get("MAVERICK_BROWSER_NO_PERSIST") != "1"
        and bool(os.environ.get("MAVERICK_BROWSER_STATE"))
    )


def _state_path() -> Path:
    override = os.environ.get("MAVERICK_BROWSER_STATE")
    return Path(os.path.expanduser(override)) if override else _DEFAULT_STATE_PATH


def _restore_state_arg() -> str | None:
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
                "screenshot", "observe", "extract_text", "extract_html",
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
            "maxProperties": _MAX_FILL_FORM_FIELDS,
            "propertyNames": {"maxLength": _MAX_FILL_FORM_SELECTOR_LENGTH},
            "additionalProperties": {
                "type": "string",
                "maxLength": _MAX_FILL_FORM_VALUE_LENGTH,
            },
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


_session: _BrowserSession | None = None
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


def _capability_denied(host: str) -> str:
    return (
        "⚠ DENIED by capability policy: browser is not granted "
        f"host {host!r}. The browser session was closed."
    )


def _browser_host_denial(url: str, allow_hosts: tuple[str, ...]) -> str | None:
    """Return a denial string if ``url`` has a host outside ``allow_hosts``."""
    if not allow_hosts:
        return None
    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except ValueError:
        return None
    if not host or any(fnmatch(host, pat) for pat in allow_hosts):
        return None
    return _capability_denied(host)


def _deny_and_close_current_page(page: Any, allow_hosts: tuple[str, ...]) -> str | None:
    url = getattr(page, "url", "") or ""
    # SSRF re-check on the URL we ACTUALLY landed on. page.goto / click / back
    # follow 3xx redirects transparently, so the front-door _is_safe_browser_url
    # check on the *requested* URL isn't enough -- a redirect to
    # http://169.254.169.254/ or another internal host would otherwise be
    # readable via screenshot / extract_*. If the current page is an http(s) URL
    # on a non-public host, close the session so nothing can read it.
    if url and _SAFE_URL_RE.match(url) and not _is_safe_browser_url(url):
        close_browser()
        host = (urlparse(url).hostname or "").strip().lower()
        return (
            f"⚠ DENIED: navigation landed on a private/internal host {host!r} "
            "(redirect to a non-public address); the browser session was closed."
        )
    denial = _browser_host_denial(url, allow_hosts)
    if denial is None:
        return None
    close_browser()
    return denial

def _is_safe_browser_url(url: str) -> bool:
    if not _SAFE_URL_RE.match(url):
        return False

    host = (urlparse(url).hostname or "").strip().lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return False

    # Resolve the host (via is_blocked_host -> getaddrinfo) rather than
    # only testing a literal ipaddress.ip_address(host). The literal-only
    # check let decimal (2130706433) and hex (0x7f000001) encodings of
    # 127.0.0.1 -- which raise ValueError but resolve to loopback -- fall
    # through as "allowed", an SSRF bypass that the sibling http_fetch
    # guard already closes. Reuse it so both guards (and the
    # MAVERICK_FETCH_ALLOW_PRIVATE escape hatch) stay consistent.
    from .http_fetch import is_blocked_host

    return not is_blocked_host(host)


def _browser_navigate(session, page, args, timeout, allow_hosts) -> str:
    url = args.get("url") or ""
    if not _is_safe_browser_url(url):
        return (
            "ERROR: URL must be http(s) and must not target localhost or "
            f"non-public IP ranges; got {url!r}"
        )
    log.info("browser.navigate %s", url)
    page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    denial = _deny_and_close_current_page(page, allow_hosts)
    if denial is not None:
        return denial
    session.save_state()  # checkpoint cookies after each navigation
    return f"navigated to {page.url} (status: loaded)"


def _browser_go_back(page, args, timeout, allow_hosts) -> str:
    page.go_back(timeout=timeout)
    denial = _deny_and_close_current_page(page, allow_hosts)
    if denial is not None:
        return denial
    return f"back -> {page.url}"


def _browser_go_forward(page, args, timeout, allow_hosts) -> str:
    page.go_forward(timeout=timeout)
    denial = _deny_and_close_current_page(page, allow_hosts)
    if denial is not None:
        return denial
    return f"forward -> {page.url}"


def _browser_click(page, args, timeout, allow_hosts) -> str:
    selector = args.get("selector")
    if not selector:
        return "ERROR: click requires selector"
    log.info("browser.click %s", selector)
    page.click(selector, timeout=timeout)
    denial = _deny_and_close_current_page(page, allow_hosts)
    if denial is not None:
        return denial
    return f"clicked {selector!r} on {page.url}"


def _browser_type(page, args, timeout) -> str:
    selector = args.get("selector")
    text = args.get("text") or ""
    if not selector:
        return "ERROR: type requires selector"
    log.info("browser.type len=%d into %s", len(text), selector)
    page.fill(selector, text, timeout=timeout)
    return f"typed {len(text)} chars into {selector!r}"


def _browser_fill_form(page, args, timeout) -> str:
    fields = args.get("fields")
    if not isinstance(fields, dict) or not fields:
        return "ERROR: fill_form requires a non-empty 'fields' object {selector: value}"
    if len(fields) > _MAX_FILL_FORM_FIELDS:
        return f"ERROR: fill_form supports at most {_MAX_FILL_FORM_FIELDS} fields"

    filled: list[str] = []
    errors: list[str] = []
    field_timeout = min(timeout, _MAX_FILL_FORM_FIELD_TIMEOUT_MS)
    total_timeout = min(timeout, _MAX_FILL_FORM_TOTAL_TIMEOUT_MS)
    deadline = time.monotonic() + (total_timeout / 1000)

    for selector, value in fields.items():
        selector = str(selector)
        value = str(value)
        if len(selector) > _MAX_FILL_FORM_SELECTOR_LENGTH:
            errors.append(f"{selector[:80]}: selector too long")
            continue
        if len(value) > _MAX_FILL_FORM_VALUE_LENGTH:
            errors.append(f"{selector}: value too long")
            continue

        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            errors.append("batch timeout")
            break
        try:
            page.fill(selector, value, timeout=min(field_timeout, remaining_ms))
            filled.append(selector)
        except Exception as e:
            errors.append(f"{selector}: {type(e).__name__}")
    log.info("browser.fill_form filled=%d errors=%d", len(filled), len(errors))
    summary = f"filled {len(filled)}/{len(fields)} field(s)"
    if errors:
        summary += "; failed: " + ", ".join(errors[:10])
    return summary


def _browser_press(page, args, timeout, allow_hosts) -> str:
    text = args.get("text") or ""
    selector = args.get("selector")
    if not text:
        return "ERROR: press requires text (key name, e.g. 'Enter')"
    if selector:
        page.press(selector, text, timeout=timeout)
    else:
        page.keyboard.press(text)
    denial = _deny_and_close_current_page(page, allow_hosts)
    if denial is not None:
        return denial
    return f"pressed {text!r}"


def _browser_scroll(page, args) -> str:
    dy = int(args.get("delta_y") or 400)
    page.evaluate(f"window.scrollBy(0, {dy})")
    return f"scrolled by {dy}"


def _browser_screenshot(page) -> str:
    png_bytes = page.screenshot(full_page=False)
    b64 = base64.b64encode(png_bytes).decode("ascii")
    log.info("browser.screenshot len=%d url=%s", len(b64), page.url)
    return f"<screenshot mime=image/png base64>{b64}</screenshot>"


def _browser_extract_text(page, args) -> str:
    selector = args.get("selector")
    if selector:
        els = page.query_selector_all(selector)
        text = "\n".join((el.inner_text() or "").strip() for el in els)[:50_000]
    else:
        # Whole-page text fallback.
        body = page.query_selector("body")
        text = (body.inner_text() or "").strip()[:50_000] if body else ""
    cleaned, warning = _scan_fetched(text)
    return warning + cleaned


def _browser_extract_html(page, args) -> str:
    selector = args.get("selector")
    if selector:
        el = page.query_selector(selector)
        return (el.inner_html() if el else "")[:100_000]
    return page.content()[:100_000]


def _browser_find_text(page, args) -> str:
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


def _browser_wait_for(page, args, timeout) -> str:
    selector = args.get("selector")
    if not selector:
        return "ERROR: wait_for requires selector"
    page.wait_for_selector(selector, timeout=timeout)
    return f"selector {selector!r} appeared"


def _browser_list_links(page) -> str:
    anchors = page.query_selector_all("a[href]")
    links = []
    for a in anchors[:100]:
        href = a.get_attribute("href") or ""
        text = (a.inner_text() or "").strip()[:80]
        links.append(f"{text!r} -> {href}")
    return "\n".join(links) if links else "no links on page"


def _observe_selector_hint(el: Any) -> str | None:
    """A best-effort, human-usable selector for an interactive element.

    Prefers a stable handle (id, name, data-testid) and falls back to a tag +
    accessible-attribute hint. Returns ``None`` if nothing useful is found.
    Never raises -- a bad element just contributes no hint.
    """
    try:
        for attr in ("id", "data-testid", "name"):
            val = el.get_attribute(attr)
            if val:
                if attr == "id":
                    return f"#{val}"
                return f"[{attr}={val!r}]"
        tag = (el.evaluate("e => e.tagName") or "").lower()
        for attr in ("aria-label", "placeholder", "type", "href"):
            val = el.get_attribute(attr)
            if val:
                return f"{tag or '*'}[{attr}={val!r}]"
        return tag or None
    except Exception:
        return None


def _browser_observe(page) -> str:
    """READ-ONLY semantic snapshot of the current page.

    Returns title + url, Playwright's accessibility tree, and a BOUNDED list of
    interactive elements (role, accessible name, selector hint) so the agent can
    act on meaning rather than pixels. Output is capped so it never floods the
    context. Read-only: never mutates the page and is never gated.
    """
    try:
        title = page.title()
    except Exception:
        title = ""
    url = getattr(page, "url", "") or ""

    # Accessibility tree (semantic structure). Bound its serialized size.
    try:
        ax = page.accessibility.snapshot()
    except Exception as e:
        ax = None
        log.debug("browser.observe accessibility snapshot failed: %s", e)
    try:
        ax_json = json.dumps(ax, ensure_ascii=False, default=str) if ax else ""
    except (TypeError, ValueError):
        ax_json = ""
    ax_truncated = len(ax_json) > _MAX_OBSERVE_AXTREE_CHARS
    if ax_truncated:
        ax_json = ax_json[:_MAX_OBSERVE_AXTREE_CHARS]

    # Bounded list of interactive elements with role + accessible name + hint.
    elements: list[dict[str, Any]] = []
    try:
        handles = page.query_selector_all(
            "a[href], button, input, select, textarea, "
            "[role=button], [role=link], [role=textbox], [contenteditable=true]",
        )
    except Exception as e:
        handles = []
        log.debug("browser.observe element query failed: %s", e)
    for el in handles:
        if len(elements) >= _MAX_OBSERVE_ELEMENTS:
            break
        try:
            role = el.get_attribute("role") or (el.evaluate("e => e.tagName") or "").lower()
            name = (
                el.get_attribute("aria-label")
                or el.get_attribute("placeholder")
                or (el.inner_text() or "").strip()
                or el.get_attribute("value")
                or el.get_attribute("name")
                or ""
            )
        except Exception:
            continue
        name = " ".join(str(name).split())[:_MAX_OBSERVE_NAME_LENGTH]
        entry: dict[str, Any] = {"role": role or "?", "name": name}
        hint = _observe_selector_hint(el)
        if hint:
            entry["selector"] = hint
        elements.append(entry)

    log.info("browser.observe url=%s elements=%d", url, len(elements))
    snapshot = {
        "title": title,
        "url": url,
        "interactive_elements": elements,
        "interactive_truncated": len(handles) > len(elements),
        "accessibility_tree": ax_json,
        "accessibility_truncated": ax_truncated,
    }
    return json.dumps(snapshot, ensure_ascii=False, default=str)


def _browser_save_session(session) -> str:
    ok = session.save_state()
    return "session saved" if ok else "session not saved (persistence disabled or no active context)"


def _parse_allow_hosts(args: dict[str, Any]) -> tuple[str, ...]:
    raw_allow_hosts = args.get("_capability_allow_hosts")
    return (
        tuple(str(pat).lower() for pat in raw_allow_hosts)
        if isinstance(raw_allow_hosts, (list, tuple, set, frozenset))
        else ()
    )


def _dispatch_browser_action(
    action: str, session, page, args, timeout, allow_hosts,
) -> str:
    """Run a single browser action against the live page. Behavior identical
    to the prior inline if/elif chain (same order, same returns)."""
    if action == "navigate":
        return _browser_navigate(session, page, args, timeout, allow_hosts)
    if action == "current_url":
        return page.url
    if action == "go_back":
        return _browser_go_back(page, args, timeout, allow_hosts)
    if action == "go_forward":
        return _browser_go_forward(page, args, timeout, allow_hosts)
    if action == "click":
        return _browser_click(page, args, timeout, allow_hosts)
    if action == "type":
        return _browser_type(page, args, timeout)
    if action == "fill_form":
        return _browser_fill_form(page, args, timeout)
    if action == "press":
        return _browser_press(page, args, timeout, allow_hosts)
    if action == "scroll":
        return _browser_scroll(page, args)
    if action == "screenshot":
        return _browser_screenshot(page)
    if action == "observe":
        return _browser_observe(page)
    if action == "extract_text":
        return _browser_extract_text(page, args)
    if action == "extract_html":
        return _browser_extract_html(page, args)
    if action == "find_text":
        return _browser_find_text(page, args)
    if action == "wait_for":
        return _browser_wait_for(page, args, timeout)
    if action == "list_links":
        return _browser_list_links(page)
    if action == "save_session":
        return _browser_save_session(session)
    return f"ERROR: unknown action {action!r}"


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
    allow_hosts = _parse_allow_hosts(args)

    if action != "navigate":
        denial = _deny_and_close_current_page(page, allow_hosts)
        if denial is not None:
            return denial

    # Per-action approval gate (mutating actions only -- navigate/click/type/
    # fill_form/press). No-op in the default auto-approve consent mode; routes
    # the action through the approval queue when gating is on. Read actions
    # (extract_*/screenshot/find_text/...) are never gated.
    denied = gate_browser_action(action, args)
    if denied is not None:
        return denied

    if browser_action_risk(action, args) == "high":
        # Bracket a high-risk action with sealed before/after captures
        # (no-op unless screenshot sealing is configured).
        return seal_bracketed(
            lambda: base64.b64encode(page.screenshot(full_page=False)).decode("ascii"),
            lambda: _dispatch_browser_action(action, session, page, args, timeout, allow_hosts),
            action=f"browser.{action}",
        )
    return _dispatch_browser_action(
        action, session, page, args, timeout, allow_hosts,
    )


def browser() -> Tool:
    """Factory: builds the browser tool."""
    return Tool(
        name="browser",
        description=(
            "Browse the web. navigate to a URL, then observe to get a compact "
            "semantic snapshot (title, url, accessibility tree, and interactive "
            "elements with roles/names/selectors) so you can act on meaning, not "
            "pixels -- prefer observe before clicking. find_text or use CSS "
            "selectors to interact (click, type, fill_form to batch-fill many "
            "inputs), extract_text or extract_html to read, screenshot to see, "
            "list_links to discover navigation. Use this for normal web tasks; "
            "use the 'computer' tool for non-DOM UIs."
        ),
        input_schema=_BROWSER_INPUT_SCHEMA,
        fn=_run_browser_action,
    )
