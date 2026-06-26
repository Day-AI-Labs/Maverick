"""Local continuous-learning skill loop: distill successful runs into a skill.

After a run succeeds, its trajectory (goal + the tools it used) is evidence of a
repeatable approach. This distills the top-k most recent successful trajectories
into a single reusable micro-skill — a ``SKILL.md`` with frontmatter (name,
triggers, tools_needed) and numbered steps — written to
``~/.maverick/learned-skills/`` so it's picked up on later runs.

Opt-in (``[self_learning] distill_local`` / ``MAVERICK_DISTILL_LOCAL=1``); default
OFF. Dependency-free: ranking is by success + recency and the synthesis is
lexical (no embedding model required), so the loop runs anywhere. ``distill`` and
``to_skill_markdown`` are pure and unit-tested; the generated skill is valid for
``maverick.skills.validate_skill_file``.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from ..paths import data_dir

_STORE = data_dir("learned-skills")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "from",
    "by", "at", "as", "is", "are", "be", "this", "that", "it", "your", "my",
    "please", "then", "into", "write", "run", "do", "make", "get", "use",
}


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def enabled() -> bool:
    if _env_true("MAVERICK_DISTILL_LOCAL"):
        return True
    try:
        from ..config import load_config
        return bool((load_config() or {}).get("self_learning", {}).get("distill_local", False))
    except Exception:  # pragma: no cover
        return False


def _keywords(texts: list[str], k: int = 3) -> list[str]:
    counts: dict[str, int] = {}
    for t in texts:
        for w in re.findall(r"[a-z0-9]+", (t or "").lower()):
            if len(w) < 3 or w in _STOPWORDS:
                continue
            counts[w] = counts.get(w, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def distill(trajectories: list[dict], *, top_k: int = 3) -> dict | None:
    """Distill successful trajectories into a skill dict, or ``None`` if none.

    Each trajectory: ``{goal, success, tools: [str], t: float}``. Picks the
    most-recent ``top_k`` successful runs, derives a kebab name + triggers from
    their goals, and unions their tools.
    """
    good = [t for t in (trajectories or []) if t.get("success")]
    if not good:
        return None
    good.sort(key=lambda t: t.get("t", 0), reverse=True)
    chosen = good[:top_k]
    goals = [str(t.get("goal", "")).strip() for t in chosen if t.get("goal")]
    if not goals:
        return None

    kws = _keywords(goals)
    name = "-".join(kws) if kws else "learned-skill"
    name = re.sub(r"[^a-z0-9-]", "", name).strip("-") or "learned-skill"

    tools: list[str] = []
    for t in chosen:
        for tool in t.get("tools", []) or []:
            if tool not in tools:
                tools.append(tool)

    triggers = []
    for g in goals:
        trg = g.lower()[:80].strip()
        if trg and trg not in triggers:
            triggers.append(trg)

    return {
        "name": name,
        "triggers": triggers,
        "tools_needed": tools,
        "summary": goals[0],
        "n_examples": len(chosen),
    }


def _utc_now_iso() -> str:
    """UTC timestamp for skill provenance (the colons in the time round-trip
    through the line-based frontmatter parser; no other punctuation)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_skill_markdown(skill: dict) -> str:
    """Render a distilled skill as a validator-compliant ``SKILL.md`` string.

    Carries machine-readable PROVENANCE in the frontmatter -- when it was
    learned, from how many examples, and by which path -- so a learned skill is
    inspectable and auditable (governed learning), not an anonymous blob. The
    validator accepts these keys and the in-memory Skill ignores them, but they
    are preserved on disk; values are kept special-char-free so the line-based
    frontmatter parser round-trips them."""
    lines = ["---", f"name: {skill['name']}", "triggers:"]
    lines += [f"  - {t}" for t in skill["triggers"]]
    if skill.get("tools_needed"):
        lines.append("tools_needed:")
        lines += [f"  - {t}" for t in skill["tools_needed"]]
    # Provenance (governed learning): structured, special-char-free values.
    lines.append(f"distilled_at: {skill.get('distilled_at') or _utc_now_iso()}")
    lines.append(f"n_examples: {int(skill.get('n_examples', 1))}")
    lines.append(f"source: {skill.get('source') or 'auto-distilled-local-v2'}")
    lines.append("---")
    lines.append("")
    lines.append("# What this does")
    lines.append("")
    lines.append(
        f"Distilled from {skill.get('n_examples', 1)} successful run(s). "
        f"Approach for: {skill.get('summary', skill['name'])}.")
    lines.append("")
    lines.append("# Steps")
    lines.append("")
    if skill.get("tools_needed"):
        for i, tool in enumerate(skill["tools_needed"], 1):
            lines.append(f"{i}. Use the `{tool}` tool as the run did before.")
    else:
        lines.append("1. Follow the approach that succeeded on similar past goals.")
    return "\n".join(lines) + "\n"


def save_skill(skill: dict, store: Path | str = _STORE) -> Path:
    """Write the distilled skill to ``<store>/<name>.md`` and return the path."""
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"{skill['name']}.md"
    path.write_text(to_skill_markdown(skill), encoding="utf-8")
    return path


def distill_and_save(trajectories: list[dict], *, top_k: int = 3,
                     store: Path | str = _STORE) -> Path | None:
    """Distill + persist in one call (opt-in caller checks ``enabled()``)."""
    skill = distill(trajectories, top_k=top_k)
    return save_skill(skill, store) if skill else None


__all__ = [
    "enabled", "distill", "to_skill_markdown", "save_skill", "distill_and_save",
]
