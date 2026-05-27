"""Playwright-driven auto-capture for session providers.

Replaces the "open DevTools, find cookie, paste into terminal" flow
with: open a real browser, sign in normally, we extract the cookies
when you're done.

Heavy optional dep (Playwright ships browser binaries). Wizard checks
for availability and falls back to the paste flow if not installed.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


# Provider -> (login_url, required_cookie_keys, completion_url_substring)
# The wizard waits until the user has navigated past completion_url_substring
# (or hit a timeout) before extracting the cookies.
CAPTURE_PROFILES: dict[str, dict] = {
    "chatgpt-session": {
        "login_url": "https://chatgpt.com/auth/login",
        "completion_substring": "chatgpt.com",
        "required_cookies": ["__Secure-next-auth.session-token"],
    },
    "claude-session": {
        "login_url": "https://claude.ai/login",
        "completion_substring": "claude.ai/chat",
        "required_cookies": ["sessionKey"],
    },
    "kimi-session": {
        "login_url": "https://kimi.com/login",
        "completion_substring": "kimi.com",
        "required_cookies": ["access_token"],
    },
    "grok-session": {
        "login_url": "https://x.com/i/flow/login",
        "completion_substring": "x.com/home",
        "required_cookies": ["auth_token", "ct0"],
    },
    "gemini-session": {
        "login_url": "https://gemini.google.com/app",
        "completion_substring": "gemini.google.com/app",
        "required_cookies": ["__Secure-1PSID"],
    },
}


def playwright_available() -> bool:
    """True if Playwright + at least one browser binary is installed."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False
    return True


def auto_capture(provider: str, timeout_seconds: int = 300) -> Optional[dict]:
    """Open a browser, wait for user to log in, return captured cookies.

    Returns None if Playwright isn't installed (caller should fall back
    to paste flow), or if the user aborts.

    timeout_seconds bounds how long we wait for the login to complete.
    The user's manual sign-in (incl. OAuth, MFA) must finish within
    that window.
    """
    profile = CAPTURE_PROFILES.get(provider)
    if profile is None:
        raise ValueError(f"no auto-capture profile for {provider!r}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.info("playwright not installed; auto-capture unavailable")
        return None

    required = set(profile["required_cookies"])
    cookies_dict: dict[str, str] = {}

    with sync_playwright() as p:
        # Channel='chrome' uses the system Chrome if installed (more
        # likely to look like a real user to bot-detection). Falls back
        # to chromium-shipped-with-playwright if unavailable.
        try:
            browser = p.chromium.launch(headless=False, channel="chrome")
        except Exception:
            browser = p.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(profile["login_url"])

            # Poll the cookie jar every 2s for the required keys, up to timeout.
            import time
            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                jar = context.cookies()
                got = {c["name"]: c["value"] for c in jar if c["name"] in required}
                if required.issubset(got.keys()):
                    cookies_dict = got
                    break
                time.sleep(2)
        finally:
            try:
                context.close()
            except Exception:
                pass
            browser.close()

    if not cookies_dict or not required.issubset(cookies_dict.keys()):
        log.warning("auto-capture timed out before all required cookies appeared")
        return None
    return {"cookies": cookies_dict}
