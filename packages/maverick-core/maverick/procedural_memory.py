"""The Hippocampus -- consolidate beneficial experience into procedural memory.

Cure the agent's amnesia. Today's agent is a brilliant colleague with total
anterograde amnesia: every session starts from zero, fine-tuning is lab-side and
forgets, RAG is a sticky note. There's no *consolidation* -- no hippocampus
writing episodic experience into durable procedural skill while you sleep.

This is that consolidation. Between shifts, the episodic record (the trajectory
store -- the fast hippocampal log) is distilled into PROCEDURAL memory: the
actions that *causally help* (positive, trustworthy effect on outcome via
``promotion_effect``), each carrying a **strength** that grows when the pattern
keeps proving itself and **decays** otherwise -- so good habits persist and stale
ones fade, *without catastrophic forgetting* (a reinforced memory never drops; an
unreinforced one fades over a few cycles). It is the positive complement of
``negative_knowledge`` (which consolidates causally-*harmful* patterns into
guardrails): this consolidates the causally-*good* ones into recallable memories.

Pure + OFF by default: consolidation runs only on the opt-in trajectory corpus,
and ``recall`` on an empty store returns nothing (no behaviour change).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from . import promotion_effect as pe

log = logging.getLogger(__name__)

# Memory dynamics: a reinforced memory climbs (reinforce > decay) toward 1.0; an
# unreinforced one fades below the retire floor within a few cycles.
_BASE = 0.5
_REINFORCE = 0.5
_DECAY = 0.25
_RETIRE_BELOW = 0.2


@dataclass(frozen=True)
class Memory:
    """A consolidated 'this action helps' habit, with a reinforcement strength."""

    action: str
    benefit: float      # causal effect on outcome (> 0)
    strength: float     # 0..1; grows on reinforcement, decays otherwise

    def to_dict(self) -> dict:
        return {"action": self.action, "benefit": self.benefit, "strength": self.strength}


def consolidate(steps, prior=(), *, decay: float = _DECAY, reinforce: float = _REINFORCE,
                base: float = _BASE, min_support: int = 8,
                retire_below: float = _RETIRE_BELOW, outcome_fn=None) -> list[Memory]:
    """One consolidation cycle: reinforce habits that still help, decay the rest.

    Beneficial = an action whose confounder-adjusted effect on outcome is
    positive with confidence (``ci_low > 0``). Priors decay by ``decay``;
    still-beneficial ones are reinforced by ``reinforce`` (net climb); new ones
    enter at ``base``; anything below ``retire_below`` is forgotten. ``outcome_fn``
    (default ``_terminal_outcome``) lets the flywheel ground consolidation in real
    consequences.
    """
    steps = list(steps)
    outcome_fn = outcome_fn or _terminal_outcome
    beneficial: dict[str, float] = {}
    for tool in {s.tool for s in steps if s.tool}:
        units = pe.units_from_trajectories(
            steps,
            treatment_fn=lambda ep, t=tool: 1 if any(s.tool == t for s in ep) else 0,
            outcome_fn=outcome_fn,
            stratum_fn=lambda ep: (ep[0].domain,),
        )
        est = pe.estimate_effect(units, adjusted_for=("domain",), min_used=min_support)
        if est.trustworthy and est.ci_low > 0.0:
            beneficial[tool] = est.effect

    out: dict[str, Memory] = {}
    for m in prior:  # decay everything first
        out[m.action] = Memory(m.action, m.benefit, max(0.0, m.strength - decay))
    for action, benefit in beneficial.items():  # then reinforce / create
        cur = out.get(action)
        strength = min(1.0, cur.strength + reinforce) if cur else base
        out[action] = Memory(action, benefit, strength)

    return sorted((m for m in out.values() if m.strength >= retire_below),
                  key=lambda m: m.strength, reverse=True)


def _terminal_outcome(ep) -> float | None:
    for s in reversed(ep):
        if getattr(s, "outcome", None) is not None:
            return float(s.outcome)
        if s.is_final and getattr(s, "verifier_confidence", None) is not None:
            return float(s.verifier_confidence)
    return None


@dataclass
class MemoryStore:
    """Persistent procedural memory (atomic, 0600), keyed by action."""

    path: Path | None = None
    _mem: dict = None  # type: ignore[assignment]
    _lock: threading.Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self._lock is None:
            self._lock = threading.Lock()
        if self._mem is None:
            self._mem = {}
        if self.path is not None:
            self._load()

    def update(self, memories) -> None:
        with self._lock:
            self._mem = {m.action: m for m in memories}
            self._save()

    def recall(self, *, top_k: int = 5) -> list[Memory]:
        """The strongest consolidated habits -- a learned prior the planner can
        prefer. Empty store -> []."""
        with self._lock:
            return sorted(self._mem.values(), key=lambda m: m.strength, reverse=True)[:top_k]

    def strength_of(self, action: str) -> float:
        with self._lock:
            m = self._mem.get(action)
            return m.strength if m else 0.0

    def _load(self) -> None:
        try:
            raw = json.loads(Path(self.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for d in (raw or []):
            try:
                m = Memory(str(d["action"]), float(d["benefit"]), float(d["strength"]))
                self._mem[m.action] = m
            except (KeyError, TypeError, ValueError):
                continue

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps([m.to_dict() for m in self._mem.values()],
                                      sort_keys=True), encoding="utf-8")
            os.replace(tmp, p)
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
        except Exception:  # pragma: no cover -- best-effort
            log.debug("procedural memory save failed", exc_info=True)


_shared: dict = {}
_shared_lock = threading.Lock()


def shared() -> MemoryStore:
    from .paths import data_dir

    path = data_dir("procedural_memory.json")
    with _shared_lock:
        store = _shared.get(path)
        if store is None:
            store = MemoryStore(path=path)
            _shared[path] = store
        return store


def reset_shared() -> None:
    with _shared_lock:
        _shared.clear()


__all__ = ["Memory", "consolidate", "MemoryStore", "shared", "reset_shared"]
