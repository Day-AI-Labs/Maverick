"""Per-rung producers -- every self-improvement phase, one governed gate.

The :mod:`maverick.self_improvement` controller owns the safety spine (beats
baseline, never widens capability, human-gated at high rungs, reversible, frozen
on verifier drift, signed + audited). This module is the set of *producers* that
turn each phase's work into a :class:`~maverick.self_improvement.Candidate` and
push it through that one gate, so no rung re-invents its own safety:

* ``propose_prompt`` / ``propose_policy`` -- Phase 4 (strategy: prompts,
  playbooks, routing policies) and Phase 2 (a trained policy/adapter, once the
  caller's RL seam has produced one).
* ``propose_tool`` -- Phase 3 (a synthesized tool earns promotion only when its
  measured success rate beats the baseline; the :class:`ToolOutcomeTracker`
  supplies that evidence).
* ``propose_verifier`` -- Phase 1 (a retrained verifier head is adopted only if
  it discriminates better than the incumbent).
* ``propose_code`` -- Phase 5 (a code self-modification must pass an
  out-of-process ``validate`` seam *before* it can even reach the gate, which
  then forces human approval + non-escalation + reversibility).
* ``propose_weights`` -- Phase 6 (a fine-tuned checkpoint, human-gated).

The GPU/codegen work (RL training, head training, diff generation, fine-tuning)
is always an injected seam supplied by the caller -- this module never fakes a
trained model; it governs *adoption* of whatever the seam produced.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .promotion_effect import EffectEstimate
from .self_improvement import (
    Candidate,
    GateResult,
    SelfImprovementController,
    Verdict,
    consider,
)

log = logging.getLogger(__name__)


# -- Phase 3 evidence: did a synthesized tool actually help? ----------------

@dataclass
class ToolOutcomeTracker:
    """Per-tool use/success tally -- the reward signal for synthesized tools."""

    path: Path | None = None
    _stats: dict[str, list[int]] = field(default_factory=dict)  # name -> [uses, wins]
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.path is not None:
            self._load()

    def record(self, name: str, success: bool) -> None:
        if not name:
            return
        with self._lock:
            s = self._stats.setdefault(name, [0, 0])
            s[0] += 1
            if success:
                s[1] += 1
            self._save()

    def success_rate(self, name: str) -> float:
        with self._lock:
            s = self._stats.get(name)
            return (s[1] / s[0]) if s and s[0] else 0.0

    def samples(self, name: str) -> int:
        with self._lock:
            s = self._stats.get(name)
            return s[0] if s else 0

    def _load(self) -> None:
        try:
            raw = json.loads(Path(self.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for k, v in (raw or {}).items():
            try:
                self._stats[str(k)] = [int(v[0]), int(v[1])]
            except (TypeError, ValueError, IndexError):
                continue

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._stats, sort_keys=True), encoding="utf-8")
            os.replace(tmp, p)
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
        except Exception:  # pragma: no cover -- best-effort
            log.debug("tool outcome save failed", exc_info=True)


# -- producers (each builds a Candidate and runs it through the one gate) ----

def _propose(rung: str, summary: str, baseline: float, candidate: float, samples: int,
             *, controller: SelfImprovementController | None = None,
             capability_widens: bool | None = None, approved: bool = False,
             rollback=None, payload=None, provenance: dict | None = None) -> Verdict:
    cand = Candidate(
        rung=rung, summary=summary, baseline_score=baseline, candidate_score=candidate,
        samples=samples, capability_widens=capability_widens, approved=approved,
        rollback=rollback, payload=payload, provenance=provenance or {},
    )
    return consider(cand, controller=controller)


def propose_prompt(summary, baseline, candidate, samples, *, rollback,
                   controller=None, **prov) -> Verdict:
    """Phase 4: a new prompt/playbook variant (no capability surface)."""
    return _propose("prompt", summary, baseline, candidate, samples,
                    controller=controller, rollback=rollback, provenance=prov)


def propose_policy(summary, baseline, candidate, samples, *, rollback,
                   capability_widens=False, approved=False, controller=None, **prov) -> Verdict:
    """Phase 2/4: a trained routing/decision policy or strategy change."""
    return _propose("policy", summary, baseline, candidate, samples,
                    controller=controller, capability_widens=capability_widens,
                    approved=approved, rollback=rollback, provenance=prov)


def propose_tool(name, tracker: ToolOutcomeTracker, baseline_success, *, rollback,
                 capability_widens=False, controller=None, **prov) -> Verdict:
    """Phase 3: promote a synthesized tool only if its measured success beats baseline."""
    return _propose(
        "tool", f"synthesized tool {name!r}", baseline_success,
        tracker.success_rate(name), tracker.samples(name),
        controller=controller, capability_widens=capability_widens,
        rollback=rollback, payload={"tool": name},
        provenance={"tool": name, **prov},
    )


def propose_with_effect(rung, summary, effect: EffectEstimate, *, rollback,
                        capability_widens=False, approved=False, controller=None,
                        **prov) -> Verdict:
    """Promote a change on its estimated CAUSAL effect (``maverick.promotion_effect``).

    Replaces the correlational ``baseline``/``candidate`` evidence with a
    confounder-adjusted effect: the candidate carries ``effect_ci_low`` so the
    controller's evidence gate requires the LOWER confidence bound of the causal
    effect to clear the margin. Every promotion records the effect, its CI, the
    naive (confounded) number for contrast, and the confounders adjusted for --
    a regulator-grade "why". Fail-closed: an untrustworthy estimate (too little
    overlap, or a placebo that leaked a non-zero effect) never reaches the gate.
    """
    provenance = {
        "kind": "causal_effect",
        "ci": [round(effect.ci_low, 6), round(effect.ci_high, 6)],
        "naive": round(effect.naive_effect, 6),
        "adjusted_for": list(effect.adjusted_for),
        "n": effect.n_used,
        "overlap": round(effect.overlap, 4),
        "placebo": round(effect.placebo_effect, 6),
        "trustworthy": effect.trustworthy,
        **prov,
    }
    cand = Candidate(
        rung=rung, summary=summary, baseline_score=0.0,
        candidate_score=effect.effect, samples=effect.n_used,
        effect_ci_low=effect.ci_low, capability_widens=capability_widens,
        approved=approved, rollback=rollback, provenance=provenance,
    )
    if not effect.trustworthy:
        return Verdict(
            cand.id, rung, False,
            (GateResult("effect_calibration", False,
                        "effect estimate not trustworthy: low overlap or placebo leak"),),
            "effect estimate not trustworthy",
        )
    return consider(cand, controller=controller)


def propose_verifier(summary, baseline_discrimination, candidate_discrimination, samples,
                     *, rollback, controller=None, **prov) -> Verdict:
    """Phase 1: adopt a retrained verifier head only if it discriminates better.

    A better *judge* doesn't widen authority, so capability is bounded by
    construction; it rides the same evidence + reversibility + freeze gates.
    """
    return _propose("policy", f"verifier update: {summary}",
                    baseline_discrimination, candidate_discrimination, samples,
                    controller=controller, capability_widens=False,
                    rollback=rollback, provenance={"kind": "verifier", **prov})


def propose_code(summary, *, validate: Callable[[], tuple[bool, str]],
                 eval_before: float, eval_after: float, samples: int, rollback,
                 approved: bool = False, capability_widens: bool | None = None,
                 controller=None, **prov) -> Verdict:
    """Phase 5: a code self-modification. Must pass an out-of-process ``validate``
    seam (sandboxed import/shape/safety check) BEFORE the gate; then the
    controller forces human approval + non-escalation + reversibility.
    """
    try:
        ok, reason = validate()
    except Exception:  # pragma: no cover -- a failing validator fails closed
        ok, reason = False, "validate seam raised"
    if not ok:
        cand_id = "code-rejected"
        return Verdict(cand_id, "code", False,
                       (GateResult("validate", False, reason or "validation failed"),),
                       reason or "validation failed")
    return _propose("code", summary, eval_before, eval_after, samples,
                    controller=controller, capability_widens=capability_widens,
                    approved=approved, rollback=rollback, provenance={"kind": "code", **prov})


def propose_weights(summary, *, eval_before: float, eval_after: float, samples: int,
                    rollback, approved: bool = False, controller=None, **prov) -> Verdict:
    """Phase 6: adopt a fine-tuned checkpoint (human-gated, reversible)."""
    return _propose("weights", summary, eval_before, eval_after, samples,
                    controller=controller, capability_widens=False,
                    approved=approved, rollback=rollback, provenance={"kind": "weights", **prov})


_tracker_shared: dict[Path, ToolOutcomeTracker] = {}
_tracker_lock = threading.Lock()


def shared_tracker() -> ToolOutcomeTracker:
    from .paths import data_dir

    path = data_dir("tool_outcomes.json")
    with _tracker_lock:
        t = _tracker_shared.get(path)
        if t is None:
            t = ToolOutcomeTracker(path=path)
            _tracker_shared[path] = t
        return t


def reset_shared_tracker() -> None:
    with _tracker_lock:
        _tracker_shared.clear()


__all__ = [
    "ToolOutcomeTracker", "shared_tracker", "reset_shared_tracker",
    "propose_prompt", "propose_policy", "propose_tool",
    "propose_verifier", "propose_code", "propose_weights",
    "propose_with_effect",
]
