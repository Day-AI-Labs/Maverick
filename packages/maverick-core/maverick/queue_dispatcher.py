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

import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

JOB_NAME = "maverick.run_goal"


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
    return payload


def _deserialize_capability(raw: Any) -> Any | None:
    """Rehydrate a queued capability grant, preserving default-open ``None``."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("queued capability payload must be a mapping")

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


def _payload(
    goal_id: int,
    *,
    max_dollars,
    max_wall_seconds,
    max_depth,
    channel,
    user_id,
    capability: Any | None,
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

    return LocalThreadDispatcher().submit(
        int(payload["goal_id"]),
        max_dollars=payload.get("max_dollars"),
        max_wall_seconds=payload.get("max_wall_seconds"),
        max_depth=payload.get("max_depth") or DEFAULT_MAX_DEPTH,
        channel=payload.get("channel"),
        user_id=payload.get("user_id"),
        capability=_deserialize_capability(payload.get("capability")),
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
