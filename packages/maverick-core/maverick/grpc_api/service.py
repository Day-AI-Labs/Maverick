"""Transport-agnostic goal service backing the gRPC surface.

The gRPC server (``server.py``) is a thin protobuf shim over this class; all the
behaviour lives here so it is unit-tested without grpc installed and could back
a second transport (REST, a queue worker) unchanged.

Three operations, mirroring the roadmap's gRPC surface:
  - ``start_goal``   -> create a goal and dispatch it for background execution.
  - ``stream_episode`` -> yield the goal's events as they land, until terminal.
  - ``cancel``       -> mark a goal cancelled (honoured at the next dispatch /
    turn boundary; in-flight cooperative cancellation rides the global
    killswitch, which the agent loop already checks).

Dependencies (the world model + the dispatcher + a thread spawner) are injected
so tests drive the whole flow with in-memory fakes.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

# A goal in one of these states is finished; streaming stops.
TERMINAL_STATUSES = frozenset({"done", "blocked", "failed", "cancelled"})


@dataclass(frozen=True)
class EventDTO:
    """One goal event, protobuf-free."""

    id: int
    goal_id: int
    agent: str
    kind: str
    content: str
    ts: float


@dataclass(frozen=True)
class GoalStatusDTO:
    goal_id: int
    status: str
    result: str | None


def _default_world():  # pragma: no cover -- exercised only with a real DB
    from ..world_model import DEFAULT_DB, open_world
    return open_world(DEFAULT_DB)


def _default_dispatch(goal_id: int, **kw) -> None:  # pragma: no cover -- real run
    from ..runner import run_goal_in_background
    run_goal_in_background(goal_id, **kw)


class GoalService:
    """Backing logic for StartGoal / StreamEpisode / Cancel.

    ``world_factory`` returns a WorldModel (a fresh one per call by default, to
    match the per-goal connection discipline the runner uses). ``dispatch``
    runs a goal in the background. ``spawn`` starts the dispatch thread (swapped
    in tests to run inline). ``sleep`` is injected so streaming tests don't wait.
    """

    def __init__(
        self,
        *,
        world_factory: Callable[[], object] = _default_world,
        dispatch: Callable[..., object] = _default_dispatch,
        spawn: Callable[[Callable[[], object]], object] | None = None,
        sleep: Callable[[float], object] = time.sleep,
        poll_interval: float = 0.5,
    ):
        self._world_factory = world_factory
        self._dispatch = dispatch
        self._spawn = spawn or self._thread_spawn
        self._sleep = sleep
        self._poll_interval = poll_interval

    @staticmethod
    def _thread_spawn(fn: Callable[[], object]) -> threading.Thread:
        t = threading.Thread(target=fn, daemon=True)
        t.start()
        return t

    def start_goal(
        self,
        title: str,
        description: str = "",
        *,
        max_dollars: float | None = None,
        max_wall_seconds: float | None = None,
        channel: str | None = None,
        user_id: str | None = None,
    ) -> int:
        """Create a goal and dispatch it for background execution. Returns the
        new goal id immediately (the run proceeds asynchronously)."""
        if not (title or "").strip():
            raise ValueError("title is required")
        world = self._world_factory()
        try:
            goal_id = int(world.create_goal(title.strip(), description or ""))
        finally:
            _close(world)

        def _run() -> None:
            self._dispatch(
                goal_id,
                max_dollars=max_dollars,
                max_wall_seconds=max_wall_seconds,
                channel=channel,
                user_id=user_id,
            )

        self._spawn(_run)
        return goal_id

    def stream_episode(
        self, goal_id: int, *, since_id: int = 0, max_seconds: float | None = None
    ) -> Iterator[EventDTO]:
        """Yield goal events in id order as they land, until the goal reaches a
        terminal status (or ``max_seconds`` elapses). A final synthetic event
        (``kind="status"``) carries the terminal status + result."""
        world = self._world_factory()
        started = time.monotonic()
        last = since_id
        try:
            while True:
                events = world.goal_events(goal_id, since_id=last)
                for e in events:
                    last = e.id
                    yield EventDTO(
                        id=e.id, goal_id=e.goal_id, agent=e.agent,
                        kind=e.kind, content=e.content, ts=e.ts,
                    )
                g = world.get_goal(goal_id)
                if g is None:
                    return
                if g.status in TERMINAL_STATUSES:
                    yield EventDTO(
                        id=last + 1, goal_id=goal_id, agent="system",
                        kind="status", content=g.status, ts=time.time(),
                    )
                    return
                if max_seconds is not None and time.monotonic() - started >= max_seconds:
                    return
                self._sleep(self._poll_interval)
        finally:
            _close(world)

    def run_goal(
        self,
        goal_id: int,
        *,
        max_dollars: float | None = None,
        max_wall_seconds: float | None = None,
        channel: str | None = None,
        user_id: str | None = None,
        max_depth: int | None = None,
        capability: Any | None = None,
    ) -> GoalStatusDTO | None:
        """Run an EXISTING goal row to completion and return its terminal
        status — the worker half of the cross-host gRPC Dispatcher (caller and
        worker must share the world DB, e.g. the Postgres backend). Returns
        None when the goal id doesn't exist here (DBs not shared / bad id)."""
        world = self._world_factory()
        try:
            if world.get_goal(goal_id) is None:
                return None
        finally:
            _close(world)
        if max_depth is None:
            from ..runner import DEFAULT_MAX_DEPTH
            max_depth = DEFAULT_MAX_DEPTH
        self._dispatch(
            goal_id,
            max_dollars=max_dollars,
            max_wall_seconds=max_wall_seconds,
            channel=channel,
            user_id=user_id,
            max_depth=max_depth,
            capability=capability,
        )
        return self.status(goal_id)

    def status(self, goal_id: int) -> GoalStatusDTO | None:
        world = self._world_factory()
        try:
            g = world.get_goal(goal_id)
            if g is None:
                return None
            return GoalStatusDTO(
                goal_id=goal_id, status=g.status, result=getattr(g, "result", None)
            )
        finally:
            _close(world)

    def cancel(self, goal_id: int) -> bool:
        """Mark a goal cancelled. Returns False if the goal doesn't exist or is
        already terminal. Honoured at the next dispatch / turn boundary."""
        world = self._world_factory()
        try:
            g = world.get_goal(goal_id)
            if g is None or g.status in TERMINAL_STATUSES:
                return False
            world.set_goal_status(goal_id, "cancelled", result="cancelled via API")
            return True
        finally:
            _close(world)


def _close(world: object) -> None:
    close = getattr(world, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # pragma: no cover -- close must never raise to caller
            pass


__all__ = [
    "EventDTO",
    "GoalStatusDTO",
    "GoalService",
    "TERMINAL_STATUSES",
]
