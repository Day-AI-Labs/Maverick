"""Live wiring of the rehearsal gate into the agent's tool path.

This is the runtime glue between the Operating Twin and a running agent: it
encodes the current context as a world-model state, lazily fits a model from the
captured Operating Record, and exposes ``gate_tool`` -- which ``agent._run_tool``
consults before executing an *elevated-risk* tool.

The product decisions, made conservatively:
  * **What to gate:** only ``high``-risk tools (host mutation / arbitrary code /
    real-world control); everything else runs unrehearsed. Decided at the call
    site via ``safety.tool_risk``.
  * **State encoding:** ``(domain, role, last_tool)`` -- general to specific, the
    ordering the backoff model needs. It must match the fit-time encoding, so
    both live here.
  * **Model + refresh:** a :class:`BackoffTransitionModel` fit from the
    trajectory store, cached and rebuilt when the corpus grows materially.

Posture (kernel rule 1): OFF by default, fail-open. With ``[rehearsal]`` disabled,
no captured data yet, or any error, ``gate_tool`` returns ``proceed`` and the
tool runs exactly as today. Only when explicitly enabled (and a model exists)
does a confident-poor or unvouchable high-risk action get held.
"""
from __future__ import annotations

import threading

from . import rehearsal
from .rehearsal import PROCEED, RehearsalVerdict

_REFRESH_EVERY = 64  # rebuild the model when the corpus grows by this many rows

_lock = threading.Lock()
_cache: dict = {}


def encode_state(domain, role, last_tool) -> tuple:
    """World-model state: general -> specific (domain, role, last_tool)."""
    return (str(domain or ""), str(role or ""), str(last_tool or ""))


def _build_model(store=None):
    """Fit a backoff world-model from the captured Operating Record (None if no
    usable data). The fit-time state encoding MUST match :func:`encode_state`."""
    from .counterfactual_rollout import transitions_from_trajectories
    from .generative_world_model import BackoffTransitionModel

    if store is None:
        from .trajectory_store import shared

        store = shared()
    try:
        steps = list(store.iter_steps())
        if not steps:
            return None

        def state_fn(ep, i):
            prev = ep[i - 1].tool if i > 0 else ""
            return encode_state(ep[i].domain, ep[i].role, prev)

        def action_fn(ep, i):
            return ep[i].tool or "finish"

        def outcome_fn(ep):
            for s in reversed(ep):
                if s.outcome is not None:
                    return s.outcome
                if s.is_final and s.verifier_confidence is not None:
                    return s.verifier_confidence
            return None

        trans = transitions_from_trajectories(
            steps, state_fn=state_fn, action_fn=action_fn, outcome_fn=outcome_fn)
        if not trans:
            return None
        return BackoffTransitionModel().fit(trans)
    except Exception:  # pragma: no cover -- model building must never break a run
        return None


def _model():
    """Cached world-model, isolated by trajectory-store path.

    The trajectory store is tenant-scoped, so the fitted model cache must be as
    well. A process-global model keyed only by row count can let one tenant's
    successful history vouch for another tenant's high-risk tool.
    """
    from .trajectory_store import shared

    try:
        store = shared()
        path = store.path
        n = store.count()
    except Exception:  # pragma: no cover
        store = None
        path = None
        n = 0
    with _lock:
        entry = _cache.get(path)
        if entry is None or entry["model"] is None or abs(n - entry["n"]) >= _REFRESH_EVERY:
            entry = {"model": _build_model(store), "n": n}
            _cache[path] = entry
        return entry["model"]


def reset_cache() -> None:
    with _lock:
        _cache.clear()


def gate_tool(*, domain, role, last_tool, tool_name) -> RehearsalVerdict:
    """Rehearse running ``tool_name`` in the current context.

    Returns ``proceed`` (fail-open) when rehearsal is disabled or no model exists
    yet; otherwise the world-model's verdict.
    """
    if not rehearsal.enabled():
        return RehearsalVerdict(PROCEED, 0.5, 0.0, 0, False, "rehearsal disabled")
    model = _model()
    if model is None:
        return RehearsalVerdict(PROCEED, 0.5, 0.0, 0, False, "no world-model yet")
    return rehearsal.gate_action(model, encode_state(domain, role, last_tool), [tool_name])


def world_model():
    """The cached Operating-Record world-model (None if no data). Public accessor
    so speculative execution shares one model with rehearsal."""
    return _model()


__all__ = ["encode_state", "gate_tool", "reset_cache", "world_model"]
