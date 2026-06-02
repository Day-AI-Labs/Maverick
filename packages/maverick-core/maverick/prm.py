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
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)

# Role vocabulary for the one-hot feature block. Order is load-bearing:
# both the LearnedPRM head and prm_train.py depend on this exact ordering.
ROLE_VOCAB = ["orchestrator", "researcher", "coder", "writer", "verifier", "other"]

# Upper bound for learned artifact architecture to avoid oversized loads.
MAX_LEARNED_PRM_HIDDEN_DIM = 1024

# Names of the 12 features produced by step_features(), in order.
FEATURE_NAMES = [
    "is_final",
    "has_error",
    "tool_succeeded",
    "has_tool",
    "prior_step_score",
    "step_index_norm",
    *[f"role_{r}" for r in ROLE_VOCAB],
]


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


def step_features(ctx: StepContext) -> list[float]:
    """Deterministic, ordered, length-12 feature vector for a step.

    The ordering MUST match FEATURE_NAMES exactly; the trained head and
    inference path both rely on it. See module-level FEATURE_NAMES.
    """
    role = (ctx.role or "").split("-", 1)[0]
    if role not in ROLE_VOCAB:
        role = "other"
    role_onehot = [1.0 if r == role else 0.0 for r in ROLE_VOCAB]
    tool_succeeded = {None: 0.0, True: 1.0, False: -1.0}[ctx.tool_succeeded]
    return [
        1.0 if ctx.is_final else 0.0,
        1.0 if ctx.error else 0.0,
        tool_succeeded,
        1.0 if ctx.tool_name else 0.0,
        float(ctx.prior_step_score),
        min(ctx.step_index / 100.0, 1.0),
        *role_onehot,
    ]


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


class LearnedPRM:
    """In-process AgentPRM head trained from trajectories (arxiv:2511.08325).

    Loads a small MLP from a model directory (head.pt + head.json) and
    scores each step from the shared `step_features` vector. Artifact
    directories must be operator-controlled and read-only to the agent;
    untrusted model files are rejected rather than loaded unsafely. torch is
    an OPTIONAL dependency: it is imported lazily on the first score(), never
    at construction. If torch is missing OR the artifact can't be loaded,
    LearnedPRM fails OPEN — it logs a warning ONCE and delegates every
    score to HeuristicPRM so the swarm never blocks on model availability.
    """
    name = "learned"

    def __init__(self, model_dir: str):
        self.model_dir = model_dir
        self._fallback = HeuristicPRM()
        self._model = None       # cached (torch_module, torch) once loaded
        self._warned = False
        self._failed = False

    def _warn_once(self, msg: str) -> None:
        if not self._warned:
            log.warning("LearnedPRM: %s; falling back to heuristic", msg)
            self._warned = True

    @staticmethod
    def _artifact_dims(meta: Mapping[str, object]) -> tuple[int, int]:
        """Validate head.json and return the expected network dimensions."""
        if meta.get("feature_names") != FEATURE_NAMES:
            raise ValueError("head.json feature_names do not match this Maverick build")
        if meta.get("role_vocab") != ROLE_VOCAB:
            raise ValueError("head.json role_vocab does not match this Maverick build")

        input_dim = int(meta.get("input_dim", len(FEATURE_NAMES)))
        if input_dim != len(FEATURE_NAMES):
            raise ValueError(
                f"head.json input_dim={input_dim} does not match expected {len(FEATURE_NAMES)}"
            )

        hidden_dim = int(meta.get("hidden_dim", 16))
        if hidden_dim < 1 or hidden_dim > MAX_LEARNED_PRM_HIDDEN_DIM:
            raise ValueError(
                f"head.json hidden_dim={hidden_dim} outside allowed range "
                f"1..{MAX_LEARNED_PRM_HIDDEN_DIM}"
            )
        return input_dim, hidden_dim

    @staticmethod
    def _validate_state_dict(state: object, torch, input_dim: int, hidden_dim: int):
        """Ensure head.pt is a tensor-only state_dict for the expected MLP."""
        expected_shapes = {
            "0.weight": (hidden_dim, input_dim),
            "0.bias": (hidden_dim,),
            "2.weight": (2, hidden_dim),
            "2.bias": (2,),
        }
        if not isinstance(state, Mapping):
            raise ValueError("head.pt did not contain a state_dict mapping")

        keys = set(state.keys())
        expected_keys = set(expected_shapes)
        if keys != expected_keys:
            raise ValueError(
                "head.pt state_dict keys mismatch "
                f"(missing={sorted(expected_keys - keys)}, extra={sorted(keys - expected_keys)})"
            )

        for key, shape in expected_shapes.items():
            value = state[key]
            if not torch.is_tensor(value):
                raise ValueError(f"head.pt state_dict[{key!r}] is not a tensor")
            if tuple(value.shape) != shape:
                raise ValueError(
                    f"head.pt state_dict[{key!r}] shape {tuple(value.shape)} "
                    f"does not match expected {shape}"
                )
        return state

    def _load(self):
        """Lazily import torch + build the cached MLP. Returns it or None."""
        if self._model is not None:
            return self._model
        if self._failed:
            return None
        try:
            import json
            from pathlib import Path

            import torch
        except Exception as e:  # torch missing
            self._failed = True
            self._warn_once(f"torch unavailable ({e})")
            return None
        try:
            d = Path(self.model_dir)
            meta = json.loads((d / "head.json").read_text(encoding="utf-8"))
            if not isinstance(meta, Mapping):
                raise ValueError("head.json did not contain an object")
            input_dim, hidden_dim = self._artifact_dims(meta)
            net = torch.nn.Sequential(
                torch.nn.Linear(input_dim, hidden_dim),
                torch.nn.ReLU(),
                torch.nn.Linear(hidden_dim, 2),
            )
            state = torch.load(d / "head.pt", map_location="cpu", weights_only=True)
            state = self._validate_state_dict(state, torch, input_dim, hidden_dim)
            net.load_state_dict(state)
            net.eval()
            self._model = (net, torch)
            return self._model
        except Exception as e:
            self._failed = True
            self._warn_once(f"could not load artifact from {self.model_dir!r} ({e})")
            return None

    def score(self, ctx: StepContext) -> StepReward:
        model = self._load()
        if model is None:
            return self._fallback.score(ctx)
        net, torch = model
        try:
            x = torch.tensor([step_features(ctx)], dtype=torch.float32)
            with torch.no_grad():
                out = torch.tanh(net(x))[0]
            return StepReward(
                promise=float(out[0]),
                progress=float(out[1]),
                confidence=0.7,
            )
        except Exception as e:
            self._warn_once(f"inference failed ({e})")
            return self._fallback.score(ctx)


def build_from_env() -> ProcessRewardModel:
    """Resolve the PRM backend from env / config.

    MAVERICK_PRM=null|heuristic|remote|learned
    MAVERICK_PRM_ENDPOINT=...  (when remote)
    MAVERICK_PRM_API_KEY=...   (when remote)
    MAVERICK_PRM_PATH=...      (when learned; model dir w/ head.pt + head.json)

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
    if kind == "learned":
        path = os.environ.get("MAVERICK_PRM_PATH")
        if not path:
            log.warning("PRM=learned but MAVERICK_PRM_PATH unset; falling back to heuristic")
            return HeuristicPRM()
        return LearnedPRM(model_dir=path)
    return NullPRM()
