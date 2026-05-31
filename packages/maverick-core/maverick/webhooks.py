"""Outbound webhooks for run events.

Users configure a list of webhook endpoints in ``~/.maverick/config.toml``:

    [webhooks]
    outbound = [
        "https://example.com/maverick-hook",
        "https://hooks.zapier.com/...",
    ]
    secret = "${MAVERICK_WEBHOOK_SECRET}"    # optional HMAC signing

When set, the kernel fires:
  - goal_created       (goal_id, title)
  - goal_finished      (goal_id, status, result)
  - episode_finished   (goal_id, episode_id, outcome, cost_dollars)
  - final_emitted      (goal_id, patch_size_bytes)

The HTTP POST body is JSON; if ``secret`` is set, an HMAC-SHA256
signature is sent in the ``X-Maverick-Signature`` header.

Webhook failures are logged but never block the run.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger(__name__)


_thread_lock = threading.Lock()
_executor = None  # type: ignore[var-annotated]


def _load_config_outbound() -> tuple[list[str], str | None]:
    try:
        from .config import load_config
        cfg = load_config()
    except Exception as e:
        log.debug("webhooks: cannot load config: %s", e)
        return [], None
    section = (cfg or {}).get("webhooks") or {}
    urls = list(section.get("outbound") or [])
    secret = section.get("secret")
    if isinstance(secret, str) and secret.startswith("${") and secret.endswith("}"):
        env_name = secret[2:-1]
        secret = os.environ.get(env_name) or None
    return urls, secret


def _sign(body: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def _get_executor():
    """Lazy-init the dispatch threadpool. Daemon threads so we don't
    block process exit."""
    global _executor
    with _thread_lock:
        if _executor is None:
            from concurrent.futures import ThreadPoolExecutor
            _executor = ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="mvk-webhook",
            )
    return _executor


def _post(url: str, body: bytes, headers: dict[str, str], timeout: float) -> None:
    try:
        import httpx
    except ImportError:
        log.warning("webhooks: httpx not installed; skipping %s", url)
        return
    try:
        resp = httpx.post(url, content=body, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            log.warning(
                "webhooks: %s returned %d: %s",
                url, resp.status_code, resp.text[:200],
            )
    except Exception as e:
        log.warning("webhooks: %s failed: %s: %s", url, type(e).__name__, e)


def fire(
    event: str,
    payload: dict[str, Any],
    *,
    urls: list[str] | None = None,
    secret: str | None = None,
    timeout: float = 5.0,
) -> int:
    """Dispatch ``event`` to all configured webhook URLs.

    Returns the number of dispatch attempts started. Returns 0 if
    no webhooks are configured (silent no-op for users who haven't
    opted in).
    """
    if urls is None and secret is None:
        urls, secret = _load_config_outbound()
    if not urls:
        return 0
    body_obj = {
        "v": 1,
        "event": event,
        "ts": time.time(),
        "payload": payload,
    }
    # Serialize defensively: fire() promises never to raise into the run
    # loop, so a non-serializable payload must degrade to a no-op, not
    # crash the caller.
    try:
        body = json.dumps(body_obj, default=str).encode("utf-8")
    except (TypeError, ValueError) as e:
        log.warning("webhook: payload not serializable, skipping: %s", e)
        return 0
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Maverick-Webhook/1.0",
        "X-Maverick-Event": event,
    }
    if secret:
        headers["X-Maverick-Signature"] = _sign(body, secret)

    executor = _get_executor()
    for url in urls:
        executor.submit(_post, url, body, dict(headers), timeout)
    return len(urls)


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify an inbound webhook signature (mirror of _sign()).

    Useful for receivers building on Maverick's webhook format.
    """
    if not signature or not signature.startswith("sha256="):
        return False
    expected = _sign(body, secret)
    return hmac.compare_digest(signature, expected)


def inbound_secret() -> str | None:
    """Resolve the HMAC secret used to authenticate inbound webhooks.

    Shares the ``[webhooks] secret`` knob with the outbound dispatcher so
    operators configure one signing key. ``MAVERICK_WEBHOOK_SECRET`` in the
    environment takes precedence for deploys that prefer env over config.
    Returns None when no secret is configured (the receiver fails closed).
    """
    env = os.environ.get("MAVERICK_WEBHOOK_SECRET")
    if env:
        return env
    _, secret = _load_config_outbound()
    return secret or None


__all__ = ["fire", "verify_signature", "inbound_secret"]
