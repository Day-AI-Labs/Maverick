"""Cascaded model routing — cheap-first escalation.

Karpathy SOTA-review prescription: cheap-first cascade
(Haiku draft -> Sonnet if verifier confidence < 0.6 OR tool-call
depth > 3 -> Opus with thinking budget on second-pass failure).

This module is a stateless picker: callers ask for a model spec
for a (role, signal) tuple, get back the best fit for the current
cost/quality budget. Defaults match May 2026 Anthropic pricing.

The cascade is opt-in; the legacy ``model_for_role`` path remains
the default. Wire by passing ``cascade=True`` to your call site or
setting ``MAVERICK_CASCADE_ROUTING=1``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .llm import MODEL_HAIKU, MODEL_OPUS, MODEL_SONNET


@dataclass
class RouteSignal:
    """Per-call info the router uses to escalate."""
    role: str = ""
    verifier_confidence: Optional[float] = None
    tool_call_depth: int = 0
    prior_attempt: int = 0           # 0 = first try, 1 = retry, etc.
    requires_thinking: bool = False  # caller knows the task needs reasoning


# Cascade thresholds (env-tunable).
ESCALATE_VERIFIER_BELOW = float(os.environ.get("MAVERICK_ESCALATE_BELOW", "0.6"))
ESCALATE_TOOL_DEPTH = int(os.environ.get("MAVERICK_ESCALATE_TOOL_DEPTH", "3"))


def pick(signal: RouteSignal) -> str:
    """Return the model spec for this signal.

    Decision tree:
      1. If this is a retry/revision (prior_attempt >= 1) OR the
         verifier rejected the previous answer with low confidence,
         escalate to Opus with thinking budget.
      2. If the task naturally needs reasoning (proposer requested
         thinking), use Opus.
      3. If the role is one that anchors the swarm (orchestrator,
         revisor), use Opus.
      4. If the role is a cheap tail (summarizer, skill_distiller),
         use Haiku.
      5. Otherwise, default to Sonnet -- the workhorse.

    All defaults can be overridden via ~/.maverick/config.toml
    `[models]` per-role; this picker is read AFTER the config check
    so user wishes win.
    """
    # User-configured per-role wins.
    try:
        from .config import get_role_model
        user_spec = get_role_model(signal.role)
        if user_spec:
            return user_spec
    except Exception:
        pass

    # Cascade escalation paths.
    if signal.prior_attempt >= 1:
        return MODEL_OPUS
    if (signal.verifier_confidence is not None
            and signal.verifier_confidence < ESCALATE_VERIFIER_BELOW):
        return MODEL_OPUS
    if signal.tool_call_depth > ESCALATE_TOOL_DEPTH:
        return MODEL_OPUS
    if signal.requires_thinking:
        return MODEL_OPUS

    # Role-based defaults.
    role = signal.role
    if role in ("orchestrator", "revisor"):
        return MODEL_OPUS
    if role in ("summarizer", "haiku-tail", "skill_distiller"):
        return MODEL_HAIKU
    if role == "verifier":
        return MODEL_SONNET
    return MODEL_SONNET


def cascade_enabled() -> bool:
    """Single source of truth for whether cascaded routing is active."""
    if os.environ.get("MAVERICK_CASCADE_ROUTING", "").lower() in ("1", "true", "yes"):
        return True
    try:
        from .config import load_config
        return bool(load_config().get("models", {}).get("cascade", False))
    except Exception:
        return False
