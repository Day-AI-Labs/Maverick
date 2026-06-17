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


def _expand_env(val: object) -> str | None:
    """Resolve a config value that may be a ``${VAR}`` env reference. Returns the
    literal string, the env var's value, or ``None`` (unset / non-string)."""
    if not isinstance(val, str):
        return str(val) if val is not None else None
    if val.startswith("${") and val.endswith("}"):
        return os.environ.get(val[2:-1]) or None
    return val or None


def _load_config_outbound() -> tuple[list[str], str | None]:
    try:
        from .config import load_config
        cfg = load_config()
    except Exception as e:
        log.debug("webhooks: cannot load config: %s", e)
        return [], None
    section = (cfg or {}).get("webhooks") or {}
    urls = list(section.get("outbound") or [])
    secret = _expand_env(section.get("secret"))
    return urls, secret


def _sign(body: bytes, secret: str, *, timestamp: str | None = None) -> str:
    """HMAC-SHA256 of the request body, optionally binding a timestamp.

    When ``timestamp`` is given it is prepended to the signed material
    (``"<ts>.".encode() + body``). This is the Maverick-CONTROLLED replay
    defence: the sender sends the same ``timestamp`` in an ``X-Maverick-
    Timestamp`` header, so a captured request can't be replayed past the
    freshness window without breaking the signature. Body-only signing
    (``timestamp=None``) is preserved for the existing receiver round-trip.
    """
    mac = hmac.new(secret.encode("utf-8"), _signed_material(body, timestamp),
                   hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def _signed_material(body: bytes, timestamp: str | None) -> bytes:
    if timestamp is None:
        return body
    return f"{timestamp}.".encode() + body


def _default_max_age() -> int:
    """Replay window (seconds) for Maverick-signed inbound webhooks.

    Config knob: ``[webhooks] max_age_seconds`` in config.toml, overridable by
    ``MAVERICK_WEBHOOK_MAX_AGE_SECONDS``. Defaults to 300s (5 min)."""
    env = os.environ.get("MAVERICK_WEBHOOK_MAX_AGE_SECONDS")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    try:
        from .config import load_config
        section = (load_config() or {}).get("webhooks") or {}
        val = section.get("max_age_seconds")
        if val is not None:
            return max(1, int(val))
    except Exception:
        pass
    return 300


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
    from .secrets import scrub
    # Outbound webhook URLs frequently carry credentials in the query string
    # (?token=, ?api_key=, presigned ?sig=); scrub before logging so they don't
    # land in the default-level logs / log aggregator verbatim.
    safe_url = scrub(url)
    try:
        import httpx  # noqa: F401  (presence check; client built via _ssrf)
    except ImportError:
        log.warning("webhooks: httpx not installed; skipping %s", safe_url)
        return
    # Route through the SSRF guard: an outbound URL comes from user config, but
    # a config that points at a loopback/metadata/internal host would let the
    # webhook dispatcher be used as an SSRF proxy. safe_client resolves once,
    # rejects any non-public address, and pins the connection (no rebind).
    try:
        from .tools._ssrf import BlockedHost, safe_client
    except Exception:  # pragma: no cover - guard unavailable
        return
    try:
        client = safe_client(url, timeout=timeout)
    except BlockedHost as e:
        log.warning("webhooks: %s blocked (SSRF guard): %s", safe_url, e)
        return
    try:
        with client:
            resp = client.post(url, content=body, headers=headers)
        if resp.status_code >= 400:
            log.warning(
                "webhooks: %s returned %d: %s",
                safe_url, resp.status_code, scrub(resp.text[:200]),
            )
    except Exception as e:
        log.warning("webhooks: %s failed: %s: %s", safe_url, type(e).__name__, scrub(str(e)))


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
        # Bind a timestamp into the signature so a receiver enforcing a max-age
        # (see verify_signature) can reject a replayed capture. The timestamp is
        # sent alongside in X-Maverick-Timestamp and is part of the signed
        # material -- it can't be altered without breaking the HMAC.
        ts = str(int(time.time()))
        headers["X-Maverick-Timestamp"] = ts
        headers["X-Maverick-Signature"] = _sign(body, secret, timestamp=ts)

    executor = _get_executor()
    for url in urls:
        executor.submit(_post, url, body, dict(headers), timeout)
    return len(urls)


def _load_handoff_target() -> tuple[str | None, str | None]:
    """The deliverable hand-off target: ``([deliverables] handoff_webhook, secret)``.

    The URL may be a literal or a ``${VAR}`` env reference; signing reuses the
    existing ``[webhooks] secret`` so a deployment configures one signing key.
    Returns ``(None, ...)`` when no hand-off endpoint is configured."""
    try:
        from .config import load_config
        cfg = load_config() or {}
    except Exception as e:  # pragma: no cover -- config never blocks the hand-off
        log.debug("webhooks: cannot load config for hand-off: %s", e)
        return None, None
    url = _expand_env((cfg.get("deliverables") or {}).get("handoff_webhook"))
    _, secret = _load_config_outbound()
    return url, secret


def fire_deliverable_handoff(payload: dict[str, Any]) -> int:
    """Push an approved deliverable to the configured system-of-record endpoint.

    A thin wrapper over :func:`fire` for the ``deliverable.approved`` event,
    routed to ``[deliverables] handoff_webhook``. Silent no-op (returns 0) when
    no endpoint is configured, and -- like ``fire`` -- never raises into the
    caller, so a sign-off is recorded whether or not the hand-off is wired."""
    url, secret = _load_handoff_target()
    if not url:
        return 0
    return fire("deliverable.approved", payload, urls=[url], secret=secret)


def verify_signature(
    body: bytes,
    signature: str,
    secret: str,
    *,
    timestamp: str | None = None,
    max_age: int | None = None,
) -> bool:
    """Verify an inbound webhook signature (mirror of _sign()).

    Useful for receivers building on Maverick's webhook format.

    When ``timestamp`` is supplied the signature must cover that timestamp
    (replay defence for the Maverick-CONTROLLED format) AND the timestamp must
    be within ``max_age`` seconds of now -- a captured-but-stale request is
    rejected even though its HMAC is otherwise valid. ``max_age`` defaults to
    ``_default_max_age()``. With ``timestamp=None`` this is the original
    body-only check, unchanged.
    """
    if not signature or not signature.startswith("sha256="):
        return False
    if timestamp is not None:
        if not _timestamp_fresh(timestamp, max_age):
            return False
    expected = _sign(body, secret, timestamp=timestamp)
    return hmac.compare_digest(signature.encode(), expected.encode())


def _timestamp_fresh(timestamp: str, max_age: int | None) -> bool:
    """True if ``timestamp`` (unix seconds) is within the replay window."""
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return False
    window = _default_max_age() if max_age is None else max_age
    # Reject both stale (replayed) and far-future (clock-skew abuse) stamps.
    return abs(time.time() - ts) <= window


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
