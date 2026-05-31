"""Process Reward Model (PRM) interface for agent step scoring.

Karpathy SOTA-review prescription + AgentPRM (arxiv:2511.08325):
the verifier today scores the FINAL answer; a real PRM scores EVERY
STEP for "promise" (P[reach goal]) and "progress" (Δ toward goal).
AgentPRM reports 8× more compute-efficient than outcome-only baselines.

This module defines the PROTOCOL — a `ProcessRewardModel` interface
that scoring backends (heuristic / learned-from-trajectories /
remote-API) implement. The agent loop is wired to consume the
interface so swapping a real trained model in later doesn't require
touching agent.py.

Three reference implementations ship:

  * NullPRM           — always returns 0.5 promise + 0.0 progress
                        (back-compat default; preserves prior behavior).
  * HeuristicPRM      — cheap rule-based scorer (errors → -1 promise,
                        FINAL → +1, tool-call success → +0.1 progress).
                        Useful right now, ZERO training needed.
  * RemotePRM         — POSTs to a user-deployed AgentPRM endpoint
                        (interface ready, no inference in-process).

Wave 7c: scaffold. Real RL pipeline + Klear-AgentForge / OpenResearcher
trajectory ingestion is queued for v0.3.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StepContext:
    """Snapshot the PRM sees per step. Read-only; no side effects."""
    goal_id: int
    step_index: int
    role: str               # orchestrator | researcher | coder | ...
    tool_name: str | None = None
    tool_succeeded: bool | None = None
    is_final: bool = False
    error: str | None = None
    prior_step_score: float = 0.5


@dataclass(frozen=True)
class StepReward:
    """PRM output per step.

    promise:  P[reach goal] in [-1, 1]; 0 = no signal.
    progress: Δ toward goal in [-1, 1]; positive = closer, negative = further.
    confidence: how sure the model is about its score; in [0, 1].
    """
    promise: float
    progress: float
    confidence: float = 1.0


class ProcessRewardModel(Protocol):
    def score(self, ctx: StepContext) -> StepReward: ...


class NullPRM:
    """Back-compat: no signal. The verifier still runs at FINAL."""
    name = "null"

    def score(self, ctx: StepContext) -> StepReward:
        return StepReward(promise=0.5, progress=0.0, confidence=0.0)


class HeuristicPRM:
    """Rule-based PRM — useful TODAY, no training required.

    Signals:
      - is_final + no error  → strong positive promise
      - error                → strong negative promise
      - tool succeeded       → small positive progress
      - tool failed          → small negative progress
      - long run with no FINAL → progress decays toward 0
    """
    name = "heuristic"

    def score(self, ctx: StepContext) -> StepReward:
        if ctx.error:
            return StepReward(promise=-0.5, progress=-0.1, confidence=0.8)
        if ctx.is_final:
            return StepReward(promise=1.0, progress=0.5, confidence=0.7)
        if ctx.tool_name and ctx.tool_succeeded is True:
            return StepReward(promise=0.6, progress=0.1, confidence=0.6)
        if ctx.tool_name and ctx.tool_succeeded is False:
            return StepReward(promise=0.3, progress=-0.05, confidence=0.6)
        # No tool, no FINAL — agent is thinking. Slight decay vs prior.
        return StepReward(
            promise=max(0.3, ctx.prior_step_score - 0.02),
            progress=0.0,
            confidence=0.4,
        )


class RemotePRM:
    """POST to a user-deployed AgentPRM service.

    Endpoint contract (May 2026 reference impl):
      POST /score
      body:  {"goal_id":..., "step":..., "role":..., "tool":..., ...}
      reply: {"promise": ..., "progress": ..., "confidence": ...}

    If the endpoint is unreachable, falls back to HeuristicPRM so the
    swarm never blocks on PRM availability.
    """
    name = "remote"

    def __init__(self, endpoint: str, api_key: str | None = None):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self._fallback = HeuristicPRM()

    def score(self, ctx: StepContext) -> StepReward:
        try:
            import httpx
        except ImportError:
            return self._fallback.score(ctx)
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        body = {
            "goal_id": ctx.goal_id,
            "step": ctx.step_index,
            "role": ctx.role,
            "tool": ctx.tool_name,
            "tool_succeeded": ctx.tool_succeeded,
            "is_final": ctx.is_final,
            "error": ctx.error,
            "prior_step_score": ctx.prior_step_score,
        }
        try:
            with httpx.Client(timeout=2.0) as client:
                r = client.post(self.endpoint + "/score",
                                headers=headers, json=body)
                if r.status_code >= 300:
                    return self._fallback.score(ctx)
                d = r.json()
                return StepReward(
                    promise=float(d.get("promise", 0.0)),
                    progress=float(d.get("progress", 0.0)),
                    confidence=float(d.get("confidence", 0.5)),
                )
        except Exception:
            return self._fallback.score(ctx)


def build_from_env() -> ProcessRewardModel:
    """Resolve the PRM backend from env / config.

    MAVERICK_PRM=null|heuristic|remote
    MAVERICK_PRM_ENDPOINT=...  (when remote)
    MAVERICK_PRM_API_KEY=...   (when remote)

    Default: NullPRM (preserves pre-Wave-7c behavior).
    """
    kind = os.environ.get("MAVERICK_PRM", "null").strip().lower()
    if kind == "heuristic":
        return HeuristicPRM()
    if kind == "remote":
        endpoint = os.environ.get("MAVERICK_PRM_ENDPOINT")
        if not endpoint:
            log.warning("PRM=remote but MAVERICK_PRM_ENDPOINT unset; falling back to heuristic")
            return HeuristicPRM()
        return RemotePRM(endpoint=endpoint,
                         api_key=os.environ.get("MAVERICK_PRM_API_KEY"))
    return NullPRM()
