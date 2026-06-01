"""Swarm context: shared state for all agents in a single run.

Every agent in a swarm shares:
  - one LLM client (with its own connection pool)
  - one WorldModel (persistent state)
  - one Budget (global cost/time/token cap)
  - one Blackboard (shared workspace for the run)
  - one Sandbox (execution backend)
  - one Shield (input/tool-call/output scans; may be None if disabled)
  - zero or more MCPClient instances (external tool servers via stdio)

Children inherit the parent's context but get their own brief, role, and depth.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

from .blackboard import Blackboard
from .budget import Budget
from .llm import LLM
from .world_model import WorldModel


def _default_use_skills() -> bool:
    """Whether to inject skills into agent prompts.

    Precedence: the MAVERICK_USE_SKILLS env var wins when set (the runbook
    tells operators to set MAVERICK_USE_SKILLS=0 for SWE-bench Pro runs --
    skill memorization is a contamination risk, see reproducibility-audit +
    Karpathy-review findings). When the env var is unset, fall back to the
    [features] skills config toggle (default on). Fail-soft to on so an
    unreadable config never silently disables skills.
    """
    env = os.environ.get("MAVERICK_USE_SKILLS")
    if env is not None:
        return env.lower() not in ("0", "false", "no")
    try:
        from .config import get_features
        return bool(get_features()["skills"])
    except Exception:
        return True


def _default_max_total_spawns() -> int:
    try:
        return max(1, int(os.environ.get("MAVERICK_MAX_TOTAL_SPAWNS", "64")))
    except ValueError:
        return 64


@dataclass
class SwarmContext:
    llm: LLM
    world: WorldModel
    budget: Budget
    blackboard: Blackboard
    sandbox: Any
    goal_id: int
    max_depth: int = 3
    use_skills: bool = field(default_factory=_default_use_skills)
    shield: Any | None = None
    mcp_clients: list = field(default_factory=list)
    channel: str | None = None
    user_id: str | None = None
    # Durable execution: the episode this run belongs to. Discriminates
    # best-of-N attempts (same goal_id, distinct episodes) so a resumed
    # attempt doesn't pick up a sibling's checkpoint. Defaults to 0 for
    # callers that don't checkpoint.
    episode_id: int = 0
    max_total_spawns: int = field(default_factory=_default_max_total_spawns)
    _spawns_used: int = 0
    _workdir_lock: asyncio.Lock | None = field(default=None, repr=False)

    @property
    def workdir_lock(self) -> asyncio.Lock:
        """Serialize the coding-mode apply/test/reset critical section.

        ``spawn_swarm`` runs coder children concurrently via
        ``asyncio.gather``; they all share one ``sandbox.workdir`` and
        mutate its git tree (apply patch -> run tests -> reset). Without
        a lock, two children stomp each other's working tree. Created
        lazily: a raw ``asyncio.Lock`` as a dataclass default would bind
        to whatever loop exists at construction (often none), so we make
        it on first access, which always happens inside a running loop.
        """
        if self._workdir_lock is None:
            self._workdir_lock = asyncio.Lock()
        return self._workdir_lock

    def try_reserve_spawns(self, n: int) -> bool:
        """Reserve ``n`` child-agent slots for this goal.

        ``max_depth`` + per-call fan-out alone allow an exponential herd
        (8 + 64 + 512 + ... agents) that a hijacked/confused orchestrator
        can use to burn the whole budget on attacker work before refusal.
        This bounds the TOTAL agents a single goal may create. Synchronous
        (no await between check and bump), so atomic on the event loop.
        """
        if self._spawns_used + max(0, n) > self.max_total_spawns:
            return False
        self._spawns_used += max(0, n)
        return True
