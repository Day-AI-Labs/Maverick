"""Append-only shared workspace for a single run.

Specialists never talk to each other directly. They post observations,
findings, and artifacts to the blackboard. The orchestrator reads it to
decide what to do next.

v0.1.3: blackboard now optionally mirrors entries into ``world.goal_events``
so the dashboard can stream live progress. Wiring is opt-in via
``Blackboard.attach_world(world, goal_id)`` so unit tests + the old
behavior keep working.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Entry:
    ts: float
    agent: str
    kind: str  # plan | observation | finding | artifact | error | verify
    content: str
    meta: dict[str, Any]


class Blackboard:
    def __init__(self):
        self.entries: list[Entry] = []
        self._world = None
        self._goal_id: int | None = None
        # Agent compartments: optional QuarantineRegistry. When attached, posts
        # by a sealed agent are withheld from render() so a poisoned finding
        # can't steer the rest of the swarm. None == disabled.
        self._quarantine = None
        # Guards entries against a runner thread and the event loop touching
        # the same blackboard. (NOTE: this does not serialize same-thread
        # gather() coroutines against each other — the deeper swarm-shares-
        # one-connection issue is tracked as the async-DB-offload item.)
        self._lock = threading.Lock()

    def attach_world(self, world, goal_id: int) -> None:
        """Wire the blackboard to a WorldModel so posts are persisted as events."""
        self._world = world
        self._goal_id = goal_id

    def attach_quarantine(self, registry) -> None:
        """Wire a QuarantineRegistry so sealed agents' posts are withheld."""
        self._quarantine = registry

    def _is_sealed(self, agent: str) -> bool:
        q = self._quarantine
        if q is None:
            return False
        try:
            return q.is_sealed(agent)
        except Exception:  # pragma: no cover -- containment must never break reads
            return False

    # Hard cap on retained entries so a long run (or an agent posting in a
    # loop) can't grow this list without bound. Reads only ever take a
    # bounded tail / filtered subset, so dropping the oldest entries past the
    # cap is safe. Override via MAVERICK_BLACKBOARD_MAX_ENTRIES.
    _MAX_ENTRIES = max(100, int(os.environ.get("MAVERICK_BLACKBOARD_MAX_ENTRIES", "5000")))

    def post(self, agent: str, kind: str, content: str, **meta: Any) -> None:
        with self._lock:
            self.entries.append(Entry(time.time(), agent, kind, content, meta))
            if len(self.entries) > self._MAX_ENTRIES:
                # Trim the oldest in one slice (amortised O(1) per post).
                del self.entries[: len(self.entries) - self._MAX_ENTRIES]
        # Mirror to world.goal_events for live dashboard streaming. Best-effort:
        # if the world model write fails (e.g., disk full), the in-memory
        # blackboard still works for the agent loop.
        if self._world is not None and self._goal_id is not None:
            try:
                self._world.append_event(self._goal_id, agent, kind, content)
            except Exception:
                pass

    def by_kind(self, kind: str) -> list[Entry]:
        with self._lock:
            return [e for e in self.entries if e.kind == kind]

    def by_agent(self, agent: str) -> list[Entry]:
        with self._lock:
            return [e for e in self.entries if e.agent == agent]

    def render(self, max_entries: int = 50) -> str:
        with self._lock:
            snapshot = list(self.entries)
        # Withhold sealed agents' posts (compartment Rung 1): a quarantined
        # agent's findings must not steer the orchestrator or its siblings.
        visible = [e for e in snapshot if not self._is_sealed(e.agent)]
        recent = visible[-max_entries:]
        lines = []
        for e in recent:
            head = f"[{e.agent}/{e.kind}]"
            lines.append(f"{head} {e.content}")
        return "\n".join(lines)

    def to_json(self) -> str:
        with self._lock:
            snapshot = list(self.entries)
        return json.dumps([asdict(e) for e in snapshot], indent=2)
