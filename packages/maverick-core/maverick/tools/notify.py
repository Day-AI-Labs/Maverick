"""Notification tool — agent-callable push.

Wraps the existing ``maverick.notifications.notify`` so agents can
fire ntfy/Pushover/Discord/Slack messages directly (status updates,
"task done, please review", "blocked on Q"). Channels + creds are
read from ``[notifications]`` config; the agent only chooses the
message + priority.

ops:
  - send(title, body, priority)
"""
from __future__ import annotations

from typing import Any

from . import Tool

_NOTIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "priority": {
            "type": "string",
            "enum": ["low", "default", "high", "urgent"],
        },
        "category": {
            "type": "string",
            "description": "Tag used by some backends (default 'agent').",
        },
    },
    "required": ["title"],
}


def _run(args: dict[str, Any]) -> str:
    title = (args.get("title") or "").strip()
    if not title:
        return "ERROR: notify requires title"
    body = args.get("body") or ""
    priority = (args.get("priority") or "default").strip().lower()
    if priority not in {"low", "default", "high", "urgent"}:
        priority = "default"
    category = (args.get("category") or "agent").strip()
    try:
        from ..notifications import notify
    except ImportError as e:
        return f"ERROR: notifications module unavailable: {e}"
    try:
        sent = notify(
            f"{title}\n{body}".strip() if body else title,
            priority=priority,
            category=category,
        )
    except Exception as e:
        return f"ERROR: notify failed: {type(e).__name__}: {e}"
    if not sent:
        return (
            "no notification backend is configured. "
            "Set [notifications] backend in ~/.maverick/config.toml."
        )
    return f"sent ({len(sent)} backend{'s' if len(sent) != 1 else ''})"


def notify_tool() -> Tool:
    return Tool(
        name="notify",
        description=(
            "Fire a push notification to the user via configured "
            "backends (ntfy / Pushover / Discord / Slack). Args: "
            "title (required), body, priority "
            "(low/default/high/urgent), category. Use sparingly — "
            "good for 'task complete' / 'blocked on Q' / etc."
        ),
        input_schema=_NOTIFY_SCHEMA,
        fn=_run,
    )
