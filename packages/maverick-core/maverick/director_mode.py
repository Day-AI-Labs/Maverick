"""Director mode (roadmap: 2028 H2 UX — "outcomes → plans → autonomy").

The director states an **outcome** and picks how much rope the swarm gets;
the mode assembles the run configuration from the controls that already
exist, instead of the operator hand-tuning five knobs per goal:

* **Outcome → goal**: the outcome statement becomes a plan-first goal (the
  plan-execute-reflect topology), titled and framed as a verifiable outcome
  ("Outcome: ...; done when the reflector accepts").
* **Autonomy profile → envelope**: three named profiles map to the existing
  controls — consent mode (``MAVERICK_CONSENT_MODE``), the review-checkpoint
  intervals (``review_checkpoint``), and a budget multiplier over the
  configured cap:

  ==============  ============  =======================  ================
  profile         consent       review checkpoint        budget multiple
  ==============  ============  =======================  ================
  ``supervised``  ask           every $2 / 25 calls      0.5×
  ``semi``        dashboard     every $10 / 100 calls    1.0×
  ``autonomous``  auto-approve  every $25 / 250 calls    2.0×
  ==============  ============  =======================  ================

:func:`direct` is pure assembly — it returns the goal spec + envelope (env
overrides, checkpoint policy, budget) and **starts nothing**; the caller
(CLI, dashboard, channel handler) applies it. Profiles are overridable via
``[director.profiles.<name>]`` config; unknown profiles are refused (an
autonomy level must never be guessed).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PROFILES: dict[str, dict[str, Any]] = {
    "supervised": {
        "consent_mode": "ask",
        "checkpoint": {"dollars": 2.0, "tool_calls": 25},
        "budget_multiplier": 0.5,
    },
    "semi": {
        "consent_mode": "dashboard",
        "checkpoint": {"dollars": 10.0, "tool_calls": 100},
        "budget_multiplier": 1.0,
    },
    "autonomous": {
        "consent_mode": "auto-approve",
        "checkpoint": {"dollars": 25.0, "tool_calls": 250},
        "budget_multiplier": 2.0,
    },
}


class UnknownProfileError(ValueError):
    """An autonomy level must be one of the named profiles, never guessed."""


@dataclass(frozen=True)
class DirectorRun:
    """The assembled, not-yet-started run configuration."""

    goal_title: str
    goal_description: str
    profile: str
    consent_mode: str
    checkpoint: dict          # CheckpointPolicy kwargs
    max_dollars: float
    planning_mode: str = "plan_execute_reflect"
    env_overrides: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "goal_title": self.goal_title,
            "goal_description": self.goal_description,
            "profile": self.profile,
            "consent_mode": self.consent_mode,
            "checkpoint": dict(self.checkpoint),
            "max_dollars": self.max_dollars,
            "planning_mode": self.planning_mode,
            "env_overrides": dict(self.env_overrides),
        }


def _profile(name: str) -> dict[str, Any]:
    base = PROFILES.get(name)
    if base is None:
        raise UnknownProfileError(
            f"unknown autonomy profile {name!r}; expected one of "
            f"{sorted(PROFILES)}")
    merged = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    try:
        from .config import load_config
        override = (((load_config() or {}).get("director") or {})
                    .get("profiles") or {}).get(name) or {}
        for key in ("consent_mode", "budget_multiplier"):
            if key in override:
                merged[key] = override[key]
        if isinstance(override.get("checkpoint"), dict):
            merged["checkpoint"].update(override["checkpoint"])
    except Exception:  # pragma: no cover -- config never blocks assembly
        pass
    return merged


def direct(outcome: str, *, profile: str = "supervised",
           base_max_dollars: float | None = None) -> DirectorRun:
    """Assemble a director run from an outcome statement + autonomy profile.

    ``base_max_dollars`` defaults to the configured budget cap; the profile's
    multiplier scales it (the hard Budget ceiling still applies at run time —
    this only sets the per-run cap, never bypasses ``budget.check()``).
    """
    outcome = (outcome or "").strip()
    if not outcome:
        raise ValueError("an outcome statement is required")
    p = _profile(profile)
    if base_max_dollars is None:
        from .budget import budget_from_config
        base_max_dollars = float(budget_from_config().max_dollars)
    title = outcome if len(outcome) <= 80 else outcome[:77] + "..."
    description = (
        f"Outcome: {outcome}\n\n"
        "Operate plan-first (plan -> execute -> reflect); the run is done "
        "when the reflector accepts the outcome as achieved, not when a step "
        "list is exhausted."
    )
    return DirectorRun(
        goal_title=title,
        goal_description=description,
        profile=profile,
        consent_mode=str(p["consent_mode"]),
        checkpoint=dict(p["checkpoint"]),
        max_dollars=round(base_max_dollars * float(p["budget_multiplier"]), 2),
        env_overrides={
            "MAVERICK_CONSENT_MODE": str(p["consent_mode"]),
            "MAVERICK_REVIEW_CHECKPOINT_DOLLARS": str(p["checkpoint"].get("dollars", "")),
            "MAVERICK_REVIEW_CHECKPOINT_TOOL_CALLS": str(p["checkpoint"].get("tool_calls", "")),
        },
    )


__all__ = ["PROFILES", "DirectorRun", "UnknownProfileError", "direct"]
