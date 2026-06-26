"""Queue-backed goal dispatcher — the control-plane / data-plane split.

The default :class:`~maverick.runner.LocalThreadDispatcher` runs goals in the API
process. :class:`QueueDispatcher` instead **enqueues** each goal onto a task
queue; a separate pool of workers pulls jobs and runs them with the local
dispatcher. That moves execution off the request process so one box (or tenant)
can't starve the others, and lets the worker tier scale independently.

The broker is injected as a plain ``enqueue(job_name, payload)`` callable, so the
dispatcher is unit-tested with a fake and is broker-agnostic. :func:`arq_enqueue`
is a ready adapter for **arq** (Redis), behind the ``[queue]`` extra; Celery /
Temporal / SQS are the same shape. Install it at startup with
:func:`install_from_config` (``[queue] backend = "arq"``).

``submit`` returns ``None`` (dispatched): the goal's terminal status is produced
by the worker and read back by polling, not synchronously from ``submit`` — the
same observable contract callers already use for background runs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

JOB_NAME = "maverick.run_goal"

# A capability grant rides the queue payload through the broker (Redis/arq) -- a
# storage + wire boundary. Anyone who can write to the broker could otherwise
# forge a grant: an empty ``allow_tools`` means "all tools", and a forged
# ``principal``/``ancestors`` dodges the revocation list. When a shared secret is
# configured on BOTH the enqueuing process and the worker tier, sign the grant
# (HMAC-SHA256 over its canonical fields) and verify it fail-closed on dequeue.
# Symmetric HMAC keeps key distribution to one shared secret across hosts; the
# secret is never placed on the queue, so a queue-writer cannot mint a valid sig.
_QUEUE_SIG_FIELD = "sig"
_WARNED_NO_QUEUE_KEY = False


def _queue_signing_key() -> str | None:
    """Shared secret used to sign/verify queued capability grants, or ``None``.

    Set ``MAVERICK_QUEUE_SIGNING_KEY`` (or ``[queue] signing_key``) to the SAME
    value on the API tier and every worker. Absent -> grants travel unsigned and
    the worker's local-policy intersection (``_worker_capability``) stays the
    only defense."""
    env = os.environ.get("MAVERICK_QUEUE_SIGNING_KEY", "").strip()
    if env:
        return env
    try:
        from .config import load_config
        v = ((load_config() or {}).get("queue") or {}).get("signing_key")
        return str(v).strip() or None if v else None
    except Exception:  # pragma: no cover -- config never blocks dispatch
        return None


def _capability_sig(payload: dict[str, Any], key: str) -> str:
    """HMAC-SHA256 over the canonical grant fields (excluding the sig itself)."""
    body = {k: payload[k] for k in sorted(payload) if k != _QUEUE_SIG_FIELD}
    msg = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _serialize_capability(capability: Any | None) -> dict[str, Any] | None:
    """Return a JSON-safe representation of an explicit capability grant."""
    if capability is None:
        return None

    from .capability import Capability

    if not isinstance(capability, Capability):
        raise TypeError(
            "queue dispatch requires capability to be a maverick.capability.Capability"
        )
    payload = {
        "principal": capability.principal,
        "allow_tools": sorted(capability.allow_tools),
        "deny_tools": sorted(capability.deny_tools),
        "max_risk": capability.max_risk,
        "expires_at": capability.expires_at,
        "allow_paths": sorted(capability.allow_paths),
        "allow_hosts": sorted(capability.allow_hosts),
    }
    if capability.ancestors:
        payload["ancestors"] = list(capability.ancestors)
    key = _queue_signing_key()
    if key:
        payload[_QUEUE_SIG_FIELD] = _capability_sig(payload, key)
    return payload


def _deserialize_capability(raw: Any) -> Any | None:
    """Rehydrate a queued capability grant, preserving default-open ``None``.

    Fails closed when a queue signing key is configured: a missing or invalid
    signature means the grant cannot be trusted, so the job is refused rather
    than run under an unverifiable (possibly forged) authority."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("queued capability payload must be a mapping")

    key = _queue_signing_key()
    if key:
        sig = raw.get(_QUEUE_SIG_FIELD)
        expected = _capability_sig(raw, key)
        if not (isinstance(sig, str) and hmac.compare_digest(sig, expected)):
            raise ValueError(
                "queued capability signature missing or invalid -- refusing to "
                "run under an unverifiable grant"
            )
    else:
        global _WARNED_NO_QUEUE_KEY
        if not _WARNED_NO_QUEUE_KEY:
            _WARNED_NO_QUEUE_KEY = True
            try:
                from .capability import capability_enforced
                if capability_enforced():
                    log.warning(
                        "capability enforcement is on but MAVERICK_QUEUE_SIGNING_KEY "
                        "is unset; queued grants are unsigned and trusted only via "
                        "the worker's local-policy intersection. Set a shared "
                        "signing key on the API and worker tiers."
                    )
            except Exception:  # pragma: no cover
                pass

    from .capability import Capability

    return Capability(
        principal=str(raw["principal"]),
        allow_tools=frozenset(raw.get("allow_tools") or ()),
        deny_tools=frozenset(raw.get("deny_tools") or ()),
        max_risk=raw.get("max_risk"),
        expires_at=raw.get("expires_at"),
        allow_paths=frozenset(raw.get("allow_paths") or ()),
        allow_hosts=frozenset(raw.get("allow_hosts") or ()),
        ancestors=tuple(str(p) for p in (raw.get("ancestors") or ()) if str(p)),
    )


def _worker_capability(
    capability: Any | None, *, channel: str | None = None, user_id: str | None = None,
) -> Any | None:
    """Attenuate a queued capability grant by the WORKER's own local policy.

    A job payload travels through the queue backend (Redis/arq) — a storage and
    wire boundary. Being on the queue is not proof the grant is a trusted,
    least-privilege one for THIS worker, which may run on a different host with a
    tighter policy. When capability enforcement is on, intersect the deserialized
    grant with the worker's local policy so a distributed worker enforces its own
    ceiling and can only narrow, never broaden it — mirroring the gRPC RunGoal
    path (``grpc_api.server._rpc_capability``). Default-open (``None``) is
    preserved; with enforcement off the grant is returned unchanged.
    """
    if capability is None:
        return None
    from .capability import capability_enforced, capability_from_config
    if not capability_enforced():
        return capability
    local = capability_from_config(
        principal=f"user:{user_id or 'local'}", channel=channel, user_id=user_id)
    return local.intersect(capability, principal=local.principal)


def _payload(
    goal_id: int,
    *,
    max_dollars,
    max_wall_seconds,
    max_depth,
    channel,
    user_id,
    capability: Any | None,
    concurrency_principal: str | None = None,
) -> dict:
    """JSON-safe job payload, including the explicit security capability grant."""
    return {
        "goal_id": int(goal_id),
        "max_dollars": max_dollars,
        "max_wall_seconds": max_wall_seconds,
        "max_depth": max_depth,
        "channel": channel,
        "user_id": user_id,
        "capability": _serialize_capability(capability),
        "concurrency_principal": concurrency_principal,
    }


class QueueDispatcher:
    """Enqueue goals for out-of-process execution by a worker pool."""

    def __init__(self, enqueue: Callable[[str, dict], Any]):
        self._enqueue = enqueue

    def submit(
        self,
        goal_id: int,
        *,
        max_dollars: float | None = None,
        max_wall_seconds: float | None = None,
        max_depth: int | None = None,
        channel: str | None = None,
        user_id: str | None = None,
        capability: Any | None = None,
        concurrency_principal: str | None = None,
    ) -> str | None:
        from .runner import DEFAULT_MAX_DEPTH

        payload = _payload(
            goal_id,
            max_dollars=max_dollars,
            max_wall_seconds=max_wall_seconds,
            max_depth=DEFAULT_MAX_DEPTH if max_depth is None else max_depth,
            channel=channel,
            user_id=user_id,
            capability=capability,
            concurrency_principal=concurrency_principal,
        )
        self._enqueue(JOB_NAME, payload)
        log.info("queued goal #%s for worker execution", goal_id)
        return None  # dispatched; terminal status determined by the worker


def run_queued_goal(payload: dict) -> str | None:
    """Worker-side entrypoint: execute a queued goal locally to completion.

    A queue worker (arq task, Celery task, ...) calls this with the enqueued
    payload. Returns the terminal status so the worker's own retry/backoff can
    act on a failed run."""
    from .runner import DEFAULT_MAX_DEPTH, LocalThreadDispatcher

    channel = payload.get("channel")
    user_id = payload.get("user_id")
    return LocalThreadDispatcher().submit(
        int(payload["goal_id"]),
        max_dollars=payload.get("max_dollars"),
        max_wall_seconds=payload.get("max_wall_seconds"),
        max_depth=payload.get("max_depth") or DEFAULT_MAX_DEPTH,
        channel=channel,
        user_id=user_id,
        concurrency_principal=payload.get("concurrency_principal"),
        # Re-attenuate by THIS worker's local policy before running (zero-trust
        # across the queue boundary); no-op when enforcement is off.
        capability=_worker_capability(
            _deserialize_capability(payload.get("capability")),
            channel=channel, user_id=user_id),
    )


def arq_enqueue(redis_settings: Any | None = None) -> Callable[[str, dict], None]:
    """A sync ``enqueue`` backed by **arq** (Redis). Needs the ``[queue]`` extra.

    arq is async, so each enqueue spins the coroutine to completion on a private
    loop — fine for the low-frequency "start a goal" call. Pass arq
    ``RedisSettings`` or rely on arq's defaults (localhost:6379)."""
    try:
        import asyncio

        from arq import create_pool
        from arq.connections import RedisSettings
    except ImportError as e:  # pragma: no cover -- exercised only without the extra
        raise ImportError(
            "queue backend needs arq. Run: pip install 'maverick-agent[queue]'"
        ) from e

    settings = redis_settings or RedisSettings()

    def _enqueue(
        job_name: str, payload: dict
    ) -> None:  # pragma: no cover -- needs Redis
        async def _go() -> None:
            pool = await create_pool(settings)
            try:
                await pool.enqueue_job(job_name, payload)
            finally:
                await pool.close()

        asyncio.run(_go())

    return _enqueue


def install_from_config() -> bool:
    """Install a QueueDispatcher if ``[queue] backend`` selects one. Returns True
    if a queue dispatcher was installed, False if execution stays in-process."""
    try:
        from .config import load_config

        backend = str(
            (load_config() or {}).get("queue", {}).get("backend") or ""
        ).strip()
    except Exception:  # pragma: no cover
        backend = ""
    if backend == "arq":
        from .runner import set_dispatcher

        set_dispatcher(QueueDispatcher(arq_enqueue()))
        log.info("installed arq queue dispatcher (out-of-process goal execution)")
        return True
    return False


__all__ = [
    "JOB_NAME",
    "QueueDispatcher",
    "run_queued_goal",
    "arq_enqueue",
    "install_from_config",
]
