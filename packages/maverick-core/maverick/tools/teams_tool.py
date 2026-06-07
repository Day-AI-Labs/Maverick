"""Microsoft Teams tool: post messages via an incoming webhook.

Completes the Slack/Discord/Teams trio (``slack_bot``, ``discord_bot`` already
exist). Posts a plain message or a simple title+text card to a Teams incoming
webhook URL (from the ``webhook`` arg or ``TEAMS_WEBHOOK_URL``). The webhook host
runs through the same SSRF guard as ``http_fetch``. ``_build_card`` is pure and
unit-tested; the POST is a thin ``httpx`` call tests monkeypatch.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from . import Tool

_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["send"], "default": "send"},
        "text": {"type": "string", "description": "message body (markdown)"},
        "title": {"type": "string", "description": "optional card title"},
        "webhook": {"type": "string",
                    "description": "Teams incoming webhook URL (or TEAMS_WEBHOOK_URL)"},
    },
    "required": ["text"],
}


def _build_card(text: str, title: str = "") -> dict:
    """A minimal MessageCard payload Teams accepts on incoming webhooks."""
    card: dict = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "text": text,
    }
    if title:
        card["title"] = title
        card["summary"] = title
    else:
        card["summary"] = text[:60] or "Maverick"
    return card


def _webhook(args: dict) -> str:
    return (args.get("webhook") or os.environ.get("TEAMS_WEBHOOK_URL") or "").strip()


def _run(args: dict[str, Any]) -> str:
    op = args.get("op") or "send"
    if op != "send":
        return f"ERROR: unknown op {op!r}"
    text = (args.get("text") or "").strip()
    if not text:
        return "ERROR: text is required"
    url = _webhook(args)
    if not url:
        return "ERROR: no webhook (pass 'webhook' or set TEAMS_WEBHOOK_URL)"
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "ERROR: Teams webhook must be https://"
    from .http_fetch import is_blocked_host
    if is_blocked_host(parsed.hostname or ""):
        return f"ERROR: refusing to post to private/loopback host {parsed.hostname!r}"
    try:
        import httpx
    except ImportError:
        return "ERROR: httpx not installed. Run: pip install 'maverick-agent[notifications]'"
    card = _build_card(text, (args.get("title") or "").strip())
    try:
        r = httpx.post(url, json=card, timeout=30.0)
    except Exception as e:
        return f"ERROR: Teams request failed: {type(e).__name__}: {e}"
    if r.status_code >= 400:
        return f"ERROR: Teams webhook returned {r.status_code}: {r.text[:200]}"
    return "posted to Teams"


def teams_tool() -> Tool:
    return Tool(
        name="teams",
        description=(
            "Post a message to a Microsoft Teams channel via an incoming webhook. "
            "op: send (text [+title]). Webhook from the 'webhook' arg or "
            "TEAMS_WEBHOOK_URL. Refuses non-https / private hosts."
        ),
        input_schema=_SCHEMA,
        fn=_run,
    )


__all__ = ["teams_tool", "_build_card"]
