"""Test-time skill synthesis: a temporary, task-specific skill, on the fly.

SOTA (SkillTTA arXiv 2605.16986; Trace2Skill 2603.25158): instead of relying
only on a global skill library distilled *after* success, synthesize a
short skill conditioned on *this* task's metadata + retrieved prior experience,
inject it for the current run, and discard it. Complements Maverick's existing
post-hoc distillation (``skills.py``): distillation is long-term memory, this is
working-memory scaffolding for the task in front of you.

Off by default + fail-open (``[skill_synthesis] enable`` /
``MAVERICK_SKILL_SYNTHESIS=1``). Spend is metered against the run Budget.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def enabled() -> bool:
    env = os.environ.get("MAVERICK_SKILL_SYNTHESIS", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    try:
        from .config import get_skill_synthesis
        return bool(get_skill_synthesis()["enable"])
    except Exception:  # pragma: no cover
        return False


_SYSTEM = """You write a SHORT, task-specific cheat-sheet ("skill") for an AI agent about to attempt a task.

Output 3-7 terse bullet points: the concrete steps, gotchas, and verification checks most likely to matter FOR THIS TASK. No preamble, no headings, no fluff. If you have nothing useful and specific to add, output exactly: NONE"""


async def synthesize_task_skill(
    task: str,
    llm,
    budget=None,
    *,
    retrieved: list[str] | None = None,
    max_tokens: int = 400,
) -> str | None:
    """Synthesize a temporary skill for ``task``; return its text or None.

    ``retrieved`` is optional prior-experience context (skill bodies, past
    lessons) to condition on. Returns None when disabled, on any error, or when
    the model declines (``NONE``) -- so the caller can inject unconditionally.
    """
    if not task or not task.strip():
        return None
    from .llm import model_for_role

    ctx = ""
    if retrieved:
        joined = "\n".join(f"- {r.strip()[:400]}" for r in retrieved if r and r.strip())
        if joined:
            ctx = f"\n\nRelevant prior experience:\n{joined}"
    user = f"TASK:\n{task.strip()[:2000]}{ctx}\n\nWrite the task-specific skill."
    try:
        resp = await llm.complete_async(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            tools=None,
            budget=budget,
            max_tokens=max_tokens,
            model=model_for_role("summarizer"),
        )
    except Exception as e:  # pragma: no cover -- synthesis never blocks a run
        log.debug("skill synthesis skipped: %s", e)
        return None
    text = (resp.text or "").strip()
    if not text or text.upper().startswith("NONE"):
        return None
    return text


__all__ = ["enabled", "synthesize_task_skill"]
