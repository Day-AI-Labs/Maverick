"""Glue that completes the *model-agnostic* self-improvement rungs.

These are the rungs that compound on a customer's data WITHOUT owning or
fine-tuning a generative model -- which is the whole strategy: the default brain
stays a frontier model (kernel rule 2, never compete on the model), and the moat
is governance + per-customer compounding on top of it. This module ties capture
-> evidence -> the governed controller for:

* **judgment** -- ``build_prm_examples`` turns captured trajectories into
  training rows for the small reward *head* (an MLP over the frontier model's
  outputs -- NOT an LLM, so no open-weights model is implied);
* **tools** -- ``review_generated_tools`` promotes a synthesized tool that earns
  it and retires one that doesn't;
* **prompts / skills / policies** -- ``emit_strategy_candidate`` routes a strategy
  change through the gate;
* **calibration** -- ``collect_calibration`` feeds the verifier-drift interlock
  from any ground-truth source so the freeze is always armed.

Weight-level fine-tuning (``si_producers.propose_weights`` / ``propose_policy``
on an adapter) stays an explicitly optional, sovereign-/air-gap-only seam; it is
deliberately NOT on this model-agnostic completion path.

Everything here is deterministic and offline-testable. The producers it calls
are no-ops unless ``[self_improvement] enable`` is set.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from .si_producers import ToolOutcomeTracker, propose_policy, propose_prompt, propose_tool

log = logging.getLogger(__name__)


# -- calibration: arm the verifier-drift interlock from any ground truth -----

def collect_calibration(confidence: float, correct: bool, *, source: str = "auto",
                        enabled_fn: Callable[[], bool] | None = None) -> bool:
    """Record a ``(verifier_confidence, ground_truth)`` sample when collection is on.

    Ground truth is anything trustworthy: a coding-mode test outcome, a human
    approval/denial, a hindsight regression. Feeding these keeps
    ``calibration.learning_frozen`` meaningful -- the gate that refuses to let
    the system learn from a drifting judge. No-op (returns False) when off.
    """
    try:
        from . import calibration
        on = enabled_fn() if enabled_fn is not None else calibration.collect_from_coding_enabled()
        if not on:
            return False
        return bool(calibration.record_sample(float(confidence), bool(correct), source=source))
    except Exception:  # pragma: no cover -- never block a run on calibration capture
        log.debug("calibration capture failed", exc_info=True)
        return False


# -- tools: promote what helps, retire what doesn't (Phase 3) ----------------

def should_retire(name: str, tracker: ToolOutcomeTracker, *,
                  floor: float = 0.2, min_samples: int = 5) -> bool:
    """A synthesized tool earns retirement when it has enough use and a low
    success rate -- the FORGET half of the action-space loop."""
    return tracker.samples(name) >= min_samples and tracker.success_rate(name) < floor


def review_generated_tools(names, tracker: ToolOutcomeTracker, *, baseline_success: float = 0.5,
                           rollback_for: Callable[[str], object] | None = None,
                           controller=None) -> dict[str, str]:
    """For each synthesized tool decide promote / retire / hold via the gate.

    Returns ``{name: action}`` where action is ``"promoted"``, ``"retire"``, or
    ``"hold"``. ``retire`` is advisory -- the caller removes the tool file (the
    rollback handle makes that reversible). Promotion runs through the full
    controller, so a tool that beats baseline but would widen authority is held.
    """
    rollback_for = rollback_for or (lambda n: f"retire:{n}")
    out: dict[str, str] = {}
    for name in names:
        if should_retire(name, tracker):
            out[name] = "retire"
            continue
        verdict = propose_tool(name, tracker, baseline_success,
                               rollback=rollback_for(name), capability_widens=False,
                               controller=controller)
        out[name] = "promoted" if verdict.ok else "hold"
    return out


# -- judgment: a training set for the small reward head (Phase 1) ------------

def build_prm_examples(store, *, limit: int = 10_000) -> list[dict]:
    """Turn captured trajectory steps into ``{features, promise, progress}`` rows.

    Model-agnostic: ``features`` is the deterministic 12-vector
    ``prm.step_features`` builds from a step (role one-hot, tool outcome, error,
    finality, ...). These rows train the LearnedPRM *head* (a tiny MLP) -- the
    judgment rung -- with no LLM training involved. Only steps that carry a
    promise label are emitted.
    """
    try:
        from .prm import StepContext, step_features
    except Exception:  # pragma: no cover
        return []
    rows: list[dict] = []
    for s in store.iter_steps(limit=limit):
        if s.promise is None:
            continue
        try:
            ctx = StepContext(
                goal_id=int(s.goal_id or 0), step_index=int(s.step or 0), role=s.role or "other",
                tool_name=(s.tool or None), tool_succeeded=s.tool_succeeded,
                is_final=bool(s.is_final), error=(s.error or None), prior_step_score=0.5,
            )
            rows.append({
                "features": step_features(ctx),
                "promise": float(s.promise),
                "progress": float(s.progress) if s.progress is not None else 0.0,
            })
        except Exception:  # pragma: no cover -- skip a malformed row, never crash
            continue
    return rows


# -- prompts / skills / policies (Phase 4) -----------------------------------

def emit_strategy_candidate(kind: str, summary: str, baseline: float, candidate: float,
                            samples: int, *, rollback, controller=None):
    """Route a strategy change through the gate. ``kind`` is ``"prompt"`` (a
    prompt/playbook variant, no capability surface) or ``"policy"`` (a routing/
    decision policy)."""
    if kind == "prompt":
        return propose_prompt(summary, baseline, candidate, samples,
                              rollback=rollback, controller=controller)
    return propose_policy(summary, baseline, candidate, samples,
                          rollback=rollback, capability_widens=False, controller=controller)


# -- self-harness: learn a model-specific harness addendum (Phase 4 sibling) --

def run_self_harness_pass(
    reflexions=None, *, model_id: str | None = None,
    held_in=None, held_out=None,
    score_with=None, score_without=None, propose_fn=None, controller=None,
    min_support: int = 3, limit: int = 500,
):
    """The automatic entry point for the self-harness loop (mine -> propose ->
    validate -> gate), to be called by a scheduler / the self-improvement loop.

    Resolves ``model_id`` to the configured orchestrator model and loads recent
    model-tagged reflexions when not supplied. ``score_with``/``score_without``
    are the LIVE held-in/held-out A/B over the candidate prompt -- injected by
    the caller because a real evaluation needs a real model; without them the
    pass is a dry inspection that writes nothing (mirrors the rest of this
    module: deterministic, offline-testable, no-op unless explicitly driven).
    Never raises -- a learning pass must not perturb anything.
    """
    try:
        from . import self_harness
        if not self_harness.enabled():
            return self_harness.SelfHarnessReport(model_id=str(model_id or ""))
        if not model_id:
            from .llm import model_for_role
            model_id = model_for_role("orchestrator")
        if reflexions is None:
            from . import reflexion
            reflexions = [r.to_dict() for r in reflexion.list_recent(limit=limit)]
        return self_harness.run_self_harness(
            reflexions, model_id=model_id, held_in=held_in, held_out=held_out,
            score_with=score_with, score_without=score_without,
            propose_fn=propose_fn, controller=controller, min_support=min_support)
    except Exception:  # pragma: no cover -- learning never perturbs a run
        log.debug("self-harness pass failed", exc_info=True)
        from . import self_harness
        return self_harness.SelfHarnessReport(model_id=str(model_id or ""))


__all__ = [
    "collect_calibration", "should_retire", "review_generated_tools",
    "build_prm_examples", "emit_strategy_candidate", "run_self_harness_pass",
]
