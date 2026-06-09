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


def _payload(
    goal_id: int, *, max_dollars, max_wall_seconds, max_depth, channel, user_id,
) -> dict:
    """JSON-safe job payload. ``capability`` is intentionally omitted (it is not
    serializable); the worker re-resolves it from the goal's owner/role."""
    return {
        "goal_id": int(goal_id),
        "max_dollars": max_dollars,
        "max_wall_seconds": max_wall_seconds,
        "max_depth": max_depth,
        "channel": channel,
        "user_id": user_id,
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
            max_dollars=max_dollars, max_wall_seconds=max_wall_seconds,
            max_depth=DEFAULT_MAX_DEPTH if max_depth is None else max_depth,
            channel=channel, user_id=user_id,
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

    def _enqueue(job_name: str, payload: dict) -> None:  # pragma: no cover -- needs Redis
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
        backend = str((load_config() or {}).get("queue", {}).get("backend") or "").strip()
    except Exception:  # pragma: no cover
        backend = ""
    if backend == "arq":
        from .runner import set_dispatcher
        set_dispatcher(QueueDispatcher(arq_enqueue()))
        log.info("installed arq queue dispatcher (out-of-process goal execution)")
        return True
    return False


__all__ = [
    "JOB_NAME", "QueueDispatcher", "run_queued_goal", "arq_enqueue",
    "install_from_config",
]
