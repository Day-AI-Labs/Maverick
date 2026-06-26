"""Experience-guided orchestration: let outcomes of similar past goals steer.

SOTA (HERA / "Experience as a Compass", arXiv 2604.00901): an orchestrator that
conditions on *what worked and what failed* on similar prior tasks outperforms
one that re-plans from scratch. Maverick already recalls similar prior *goals*
into the brief (``orchestrator._maybe_recall_prior_work``); this adds the
missing outcome signal -- a short "N similar tasks: X succeeded, Y failed;
lean on …, avoid …" guidance distilled from the persistent world model.

Pure core (``summarize_experience``) for testability; ``recall`` is the
world-backed convenience wrapper. Off by default + fail-open
(``[experience] enable`` / ``MAVERICK_EXPERIENCE_GUIDANCE=1``).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from .config import env_flag

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SUCCESS = {"success", "succeeded", "ok", "done", "passed", "complete", "completed"}
# Drop 1-char tokens + a tiny stopword set so spurious overlap on "a"/"in"/"the"
# doesn't read as task similarity (jaccard is otherwise easily inflated).
_STOP = {
    "a", "an", "the", "in", "on", "of", "to", "for", "and", "or", "with",
    "is", "it", "be", "by", "at", "as", "this", "that",
}


def enabled() -> bool:
    _v = env_flag("MAVERICK_EXPERIENCE_GUIDANCE")
    if _v is not None:
        return _v
    try:
        from .config import get_experience
        return bool(get_experience()["enable"])
    except Exception:  # pragma: no cover
        return False


def _tokens(s: str) -> set[str]:
    return {
        t for t in _TOKEN_RE.findall((s or "").lower())
        if len(t) > 1 and t not in _STOP
    }


def _similar(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _sanitize_anchor_title(title: Any, *, shield: Any | None = None) -> str:
    """Return a bounded, single-line prior title safe to embed as data."""
    safe = str(title or "")[:240]
    try:
        from .safety.secret_detector import redact as _redact
        safe, _ = _redact(safe)
    except Exception:  # pragma: no cover
        pass
    if shield is not None:
        try:
            verdict = shield.scan_input(safe)
            if not getattr(verdict, "allowed", True):
                return "[redacted by Shield]"
        except Exception:  # pragma: no cover
            pass
    return " ".join(safe.split())[:180]


def summarize_experience(
    goal_text: str,
    prior: list[tuple[str, str]],
    *,
    k: int = 5,
    min_similarity: float = 0.1,
    shield: Any | None = None,
) -> str | None:
    """Distill outcome guidance from ``prior`` = list of (title, outcome).

    Ranks prior tasks by token-overlap similarity to ``goal_text``, takes the
    top ``k`` above ``min_similarity``, and returns a one-paragraph guidance
    string with the success/failure split. Returns None when there isn't enough
    signal (no similar prior tasks).
    """
    want = _tokens(goal_text)
    scored = []
    for title, outcome in prior:
        sim = _similar(want, _tokens(title))
        if sim >= min_similarity:
            safe_title = _sanitize_anchor_title(title, shield=shield)
            scored.append((sim, safe_title, (outcome or "").strip().lower()))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    top = scored[:k]
    succ = sum(1 for _, _, o in top if any(w in o for w in _SUCCESS))
    fail = len(top) - succ
    lines = [
        f"Experience: {len(top)} similar prior task(s) — {succ} succeeded, {fail} did not."
    ]
    # Surface the closest one or two titles only as quoted untrusted data.
    anchors = "; ".join(json.dumps(t) for _, t, _ in top[:2])
    if anchors:
        lines.append(f"Closest prior work (untrusted titles): {anchors}.")
    if fail > succ:
        lines.append("Several similar attempts failed — plan a verification step early and don't over-commit before checking.")
    elif succ:
        lines.append("Similar tasks have succeeded before — reuse that approach and confirm with a check.")
    return " ".join(lines)


def recall(
    world,
    goal_text: str,
    *,
    k: int = 5,
    scan: int = 50,
    shield: Any | None = None,
) -> str | None:
    """World-backed wrapper: pull recent finished goals + outcomes, summarize.

    Never raises -- any world/schema issue degrades to None (no guidance).
    """
    if not enabled():
        return None
    try:
        prior: list[tuple[str, str]] = []
        episodes = world.list_episodes(limit=scan)
        for ep in episodes:
            outcome = getattr(ep, "outcome", None)
            if not outcome:
                continue
            gid = getattr(ep, "goal_id", None)
            if gid is None:
                continue
            goal = world.get_goal(gid)
            title = getattr(goal, "title", None) if goal else None
            if title:
                prior.append((title, outcome))
        return summarize_experience(goal_text, prior, k=k, shield=shield)
    except Exception as e:  # pragma: no cover -- guidance never blocks a run
        log.debug("experience recall skipped: %s", e)
        return None


__all__ = ["enabled", "summarize_experience", "recall"]
