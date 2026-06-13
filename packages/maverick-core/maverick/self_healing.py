"""Self-healing UX (roadmap: 2028 H2 UX).

When a run fails, the user shouldn't have to reverse-engineer the fix from a
stack trace. This maps a failure (the goal's terminal ``result`` text and/or
the exception) to its **failure class** and an ordered list of concrete
remedies — each with the exact command or config edit, and whether it's safe
to apply automatically (only ever config-suggestion-shaped; nothing is
auto-applied here — surfacing is the healing, the human stays in charge).

``diagnose(failure_text)`` is the pure classifier; ``remedies(cls)`` the
catalog; ``heal_report(world, goal_id)`` the per-goal entry point the
CLI/dashboard render after a failed run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Remedy:
    summary: str
    command: str          # the exact thing to run/edit
    auto_safe: bool = False   # reversible config-only suggestion


# failure class -> (detector regex over the failure text, remedies)
_CATALOG: dict[str, tuple[re.Pattern, list[Remedy]]] = {
    "budget_exceeded": (
        re.compile(r"budget|BudgetExceeded|\$\d+.*>\s*\$\d+|over.*cap", re.IGNORECASE),
        [
            Remedy("Re-run with a higher cap for this goal",
                   "maverick start \"...\" --max-dollars <higher>"),
            Remedy("Let budgets learn per task class",
                   "[budget] self_tuning = true", auto_safe=True),
            Remedy("Cut context spend on long histories",
                   "[context] compaction_strategy = \"streaming\"",
                   auto_safe=True),
        ],
    ),
    "provider_auth": (
        re.compile(r"401|403|invalid.*api.?key|authentication|unauthorized", re.IGNORECASE),
        [
            Remedy("Check the provider key in the env file",
                   "edit ~/.maverick/.env (chmod 600) and re-run"),
            Remedy("Verify which provider each role uses",
                   "maverick whoami && maverick status"),
        ],
    ),
    "rate_limited": (
        re.compile(r"429|rate.?limit|overloaded|quota.*exceeded", re.IGNORECASE),
        [
            Remedy("Enable provider failover on 429s",
                   "[failover] enabled = true", auto_safe=True),
            Remedy("Spread bulk roles onto a cheaper provider",
                   "[routing.roles.researcher] provider allow-list"),
        ],
    ),
    "shield_blocked": (
        re.compile(r"blocked by shield|BLOCKED by Shield", re.IGNORECASE),
        [
            Remedy("Review what fired and why",
                   "maverick audit verify && check the dashboard oversight page"),
            Remedy("If a false positive, calibrate the shield",
                   "python -m maverick_shield.redteam --calibrate"),
        ],
    ),
    "sandbox_missing": (
        re.compile(r"docker not available|sandbox.*not available|"
                   r"wasmtime not on PATH|libreoffice not on PATH", re.IGNORECASE),
        [
            Remedy("Install the backend the config selects, or switch",
                   "[sandbox] backend = \"local\"  # least isolated; prefer "
                   "installing docker"),
        ],
    ),
    "timeout": (
        re.compile(r"timeout|timed out|deadline", re.IGNORECASE),
        [
            Remedy("Raise the per-command sandbox timeout",
                   "[sandbox] timeout = 300", auto_safe=True),
            Remedy("Give the run a review heartbeat instead of a hard wall",
                   "[safety] review_checkpoint  # dollars/tool_calls",
                   auto_safe=True),
        ],
    ),
    "killswitch": (
        re.compile(r"killswitch|HALT", re.IGNORECASE),
        [
            Remedy("The hard stop was used; clear it deliberately",
                   "rm ~/.maverick/HALT  # then re-run the goal"),
        ],
    ),
}

UNKNOWN_REMEDIES = [
    Remedy("Replay the run to see where it diverged",
           "maverick replay <goal_id>"),
    Remedy("Check run health + recent provider errors",
           "maverick diag"),
]


def diagnose(failure_text: str) -> str:
    """Classify a failure text; 'unknown' when nothing matches."""
    text = failure_text or ""
    for cls, (pattern, _r) in _CATALOG.items():
        if pattern.search(text):
            return cls
    return "unknown"


def remedies(failure_class: str) -> list[Remedy]:
    if failure_class in _CATALOG:
        return list(_CATALOG[failure_class][1])
    return list(UNKNOWN_REMEDIES)


def heal_report(world, goal_id: int) -> str:
    """The per-goal healing view for the CLI/dashboard after a failure."""
    try:
        goal = world.get_goal(goal_id)
    except Exception:
        goal = None
    if goal is None:
        return f"goal #{goal_id} not found."
    status = getattr(goal, "status", "")
    result = getattr(goal, "result", "") or ""
    if status not in ("failed", "blocked", "cancelled"):
        return f"goal #{goal_id} is {status!r} — nothing to heal."
    cls = diagnose(result)
    lines = [f"goal #{goal_id} {status}: {result[:160]}",
             f"diagnosis: {cls}",
             "suggested remedies (nothing auto-applied):"]
    for i, r in enumerate(remedies(cls), 1):
        tag = " [safe config change]" if r.auto_safe else ""
        lines.append(f"  {i}. {r.summary}{tag}")
        lines.append(f"     -> {r.command}")
    return "\n".join(lines)


__all__ = ["Remedy", "diagnose", "remedies", "heal_report"]
