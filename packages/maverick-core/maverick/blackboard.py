"""Append-only shared workspace for a single run.

Specialists never talk to each other directly. They post observations,
findings, and artifacts to the blackboard. The orchestrator reads it to
decide what to do next.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
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

    def post(self, agent: str, kind: str, content: str, **meta: Any) -> None:
        self.entries.append(Entry(time.time(), agent, kind, content, meta))

    def by_kind(self, kind: str) -> list[Entry]:
        return [e for e in self.entries if e.kind == kind]

    def by_agent(self, agent: str) -> list[Entry]:
        return [e for e in self.entries if e.agent == agent]

    def render(self, max_entries: int = 50) -> str:
        recent = self.entries[-max_entries:]
        lines = []
        for e in recent:
            head = f"[{e.agent}/{e.kind}]"
            lines.append(f"{head} {e.content}")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps([asdict(e) for e in self.entries], indent=2)
