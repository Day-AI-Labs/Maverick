"""Push notifications for run events.

Wraps the most common consumer push services:
  - ntfy.sh (default, no account required; just a topic)
  - Pushover (PUSHOVER_USER_KEY + PUSHOVER_APP_TOKEN)
  - Discord webhook (DISCORD_NOTIFY_WEBHOOK_URL)
  - Slack webhook (SLACK_NOTIFY_WEBHOOK_URL)

Config (in ~/.maverick/config.toml):

    [notifications]
    backend = "ntfy"             # ntfy | pushover | discord | slack | none
    ntfy_topic = "${MAVERICK_NTFY_TOPIC}"
    ntfy_server = "https://ntfy.sh"

Use:

    from maverick.notifications import notify
    notify("Run #42 finished", priority="default", category="run")

Failures are logged but never block the caller. Multiple backends can
be configured; each fires its own notification.
"""
from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger(__name__)


_executor = None  # type: ignore[var-annotated]
_executor_lock = threading.Lock()


def _get_executor():
    global _executor
    with _executor_lock:
        if _executor is None:
            from concurrent.futures import ThreadPoolExecutor
            _executor = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="mvk-notify",
            )
    return _executor


def _resolve_env_ref(value: str | None) -> str | None:
    """Resolve `${ENV_VAR}` references in config strings."""
    if not value:
        return value
    if value.startswith("${") and value.endswith("}"):
        env_name = value[2:-1]
        return os.environ.get(env_name)
    return value


def _load_config() -> dict:
    try:
        from .config import load_config
        return (load_config() or {}).get("notifications") or {}
    except Exception:
        return {}


def _send_ntfy(title: str, body: str, priority: str, server: str, topic: str) -> bool:
    try:
        import httpx
    except ImportError:
        return False
    if not topic:
        return False
    prio_map = {"low": "1", "default": "3", "high": "4", "max": "5"}
    headers = {
        # The title is agent-controlled (the notify tool lets the model set
        # it). Strip CR/LF so it can't inject extra ntfy control headers /
        # split the header block.
        "Title": title.replace("\r", " ").replace("\n", " "),
        "Priority": prio_map.get(priority, "3"),
    }
    try:
        # ntfy topics are [A-Za-z0-9_-]; reject anything else so a typo/hostile
        # topic with '/'/'..'/'?'/'#' can't post to a different path on the server.
        import re as _re
        if not _re.fullmatch(r"[A-Za-z0-9_-]+", topic or ""):
            log.warning("notify ntfy: invalid topic %r (allowed: A-Za-z0-9_-)", topic)
            return False
        url = f"{server.rstrip('/')}/{topic}"
        resp = httpx.post(url, content=body.encode("utf-8"), headers=headers, timeout=10.0)
        return resp.status_code < 400
    except Exception as e:
        log.warning("notify ntfy failed: %s", e)
        return False


def _send_pushover(title: str, body: str, priority: str) -> bool:
    user = os.environ.get("PUSHOVER_USER_KEY")
    app = os.environ.get("PUSHOVER_APP_TOKEN")
    if not user or not app:
        return False
    try:
        import httpx
    except ImportError:
        return False
    prio_map = {"low": "-1", "default": "0", "high": "1", "max": "2"}
    try:
        resp = httpx.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": app, "user": user,
                "title": title, "message": body,
                "priority": prio_map.get(priority, "0"),
            },
            timeout=10.0,
        )
        return resp.status_code < 400
    except Exception as e:
        log.warning("notify pushover failed: %s", e)
        return False


def _send_discord(title: str, body: str, url: str) -> bool:
    if not url:
        return False
    try:
        import httpx
        resp = httpx.post(
            url,
            # allowed_mentions parse:[] so an agent-controlled title/body
            # containing @everyone/@here can't trigger a mass ping.
            json={
                "content": f"**{title}**\n{body}",
                "allowed_mentions": {"parse": []},
            },
            timeout=10.0,
        )
        return resp.status_code < 400
    except Exception as e:
        log.warning("notify discord failed: %s", e)
        return False


def _send_slack(title: str, body: str, url: str) -> bool:
    if not url:
        return False
    try:
        import httpx
        resp = httpx.post(
            url,
            json={"text": f"*{title}*\n{body}"},
            timeout=10.0,
        )
        return resp.status_code < 400
    except Exception as e:
        log.warning("notify slack failed: %s", e)
        return False


def notify(
    body: str,
    *,
    title: str = "Maverick",
    priority: str = "default",
    category: str | None = None,
    backends: list[str] | None = None,
    async_dispatch: bool = True,
    batch: bool = True,
) -> int:
    """Send a notification. Returns the number of backends fired.

    ``priority`` is one of: low / default / high / max.
    ``backends`` overrides config (e.g. ['ntfy']). None = use config.
    ``async_dispatch=False`` runs synchronously (mainly for tests).
    ``batch`` lets opt-in **notification batching** coalesce low/normal-priority
    pushes (``[notifications] batch_window_seconds``); high/urgent always go
    straight through, and with batching unconfigured this is a no-op. When an
    item is queued for a later batch, the call returns 0 (fired *now*).
    """
    cfg = _load_config()
    # Normalize: backend names are user-typed (config/TOML or the `backends`
    # arg) and matched case-sensitively in _dispatch ("ntfy"/"discord"/...), so
    # "Discord" / "Ntfy" / "None" would otherwise dispatch to no handler or
    # skip the "none" filter -- a user who configured notifications silently
    # gets none. Lowercase + strip; drop empties and the "none" sentinel.
    requested = [
        b.strip().lower()
        for b in (backends or [cfg.get("backend", "ntfy")])
        if isinstance(b, str) and b.strip().lower() not in ("", "none")
    ]
    if not requested:
        return 0

    # Opt-in batching: coalesce low/normal-priority pushes into a windowed
    # digest. High/urgent bypass; sync sends (tests, and the batcher's own
    # delivery) bypass so there's no recursion. No-op unless configured.
    if batch and async_dispatch and priority not in ("high", "max", "urgent"):
        from .notification_batcher import shared as _shared_batcher
        batcher = _shared_batcher()
        if batcher is not None:
            return batcher.submit(body, title=title, priority=priority,
                                  category=category)

    def _dispatch(backend: str) -> bool:
        if backend == "ntfy":
            topic = _resolve_env_ref(cfg.get("ntfy_topic"))
            server = _resolve_env_ref(cfg.get("ntfy_server")) or "https://ntfy.sh"
            if not topic:
                topic = os.environ.get("MAVERICK_NTFY_TOPIC")
            if not topic:
                log.debug("notify ntfy: no topic configured")
                return False
            return _send_ntfy(title, body, priority, server, topic)
        if backend == "pushover":
            return _send_pushover(title, body, priority)
        if backend == "discord":
            url = _resolve_env_ref(cfg.get("discord_webhook")) or \
                  os.environ.get("DISCORD_NOTIFY_WEBHOOK_URL")
            return _send_discord(title, body, url or "")
        if backend == "slack":
            url = _resolve_env_ref(cfg.get("slack_webhook")) or \
                  os.environ.get("SLACK_NOTIFY_WEBHOOK_URL")
            return _send_slack(title, body, url or "")
        log.warning("notify: unknown backend %r", backend)
        return False

    if async_dispatch:
        exec_ = _get_executor()
        for backend in requested:
            exec_.submit(_dispatch, backend)
        return len(requested)
    # Sync (for tests).
    fired = 0
    for backend in requested:
        if _dispatch(backend):
            fired += 1
    return fired


__all__ = ["notify"]
