"""Auto-skill distillation v2 (roadmap: 2027 H1 capabilities).

v1 (:mod:`maverick.skill_distillation_local`) distills recent successful runs
into a ``SKILL.md`` — but it runs after *every* goal, so a learned-skills store
slowly fills with near-duplicates of the same lesson, and a one-off success can
mint a skill that never recurs. v2 adds the two quality gates that make
continuous learning actually usable:

* **gate on evidence** — don't distill from fewer than ``min_examples``
  successful trajectories (a single success is noise, not a repeatable skill);
* **dedup against the store** — don't save a skill whose content is already
  covered by one already learned (lexical **overlap/containment** over the skill
  text — the right metric when a compact candidate is checked against a fuller
  saved skill; same zero-dep / no-embedding-model approach v1 uses), so the
  store stays a set of *distinct* lessons.

Pure and deterministic: the gates take plain skill dicts / signatures, tested
without touching disk; ``distill_and_save_gated`` is the drop-in the loop calls.
"""
from __future__ import annotations

import re
from pathlib import Path

from .skill_distillation_local import _STORE, distill, save_skill

# A small stop-list so the signature is content words, not glue.
_STOP = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "into", "your", "you",
    "are", "was", "use", "using", "skill", "learned", "step", "steps", "when",
    "then", "run", "goal", "task",
})

DEFAULT_MIN_EXAMPLES = 2
DEFAULT_DEDUP_THRESHOLD = 0.6


def _tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return frozenset(w for w in words if len(w) >= 3 and w not in _STOP)


def _signature(skill: dict) -> frozenset[str]:
    parts = [skill.get("name", ""), skill.get("summary", "")]
    parts += list(skill.get("triggers", []) or [])
    parts += list(skill.get("tools_needed", []) or [])
    return _tokens(" ".join(str(p) for p in parts))


def _overlap(a: frozenset, b: frozenset) -> float:
    """Overlap (containment) coefficient: ``|a∩b| / min(|a|,|b|)``.

    Unlike Jaccard, this isn't deflated when one set is much larger — what we
    want when a compact candidate skill is checked against a fuller saved one.
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def is_duplicate(signature: frozenset[str], existing: list[frozenset[str]], *,
                 threshold: float = DEFAULT_DEDUP_THRESHOLD) -> bool:
    return any(_overlap(signature, e) >= threshold for e in existing)


def signatures_from_store(store: Path | str = _STORE) -> list[frozenset[str]]:
    """Content signatures of every already-learned skill in ``store``."""
    p = Path(store)
    if not p.exists():
        return []
    out: list[frozenset[str]] = []
    for md in sorted(p.glob("*.md")):
        try:
            out.append(_tokens(md.read_text(encoding="utf-8")))
        except OSError:
            continue
    return out


def distill_gated(trajectories: list[dict], *,
                  existing_signatures: list[frozenset[str]] | None = None,
                  top_k: int = 3, min_examples: int = DEFAULT_MIN_EXAMPLES,
                  dedup_threshold: float = DEFAULT_DEDUP_THRESHOLD) -> tuple[dict | None, str]:
    """Distill with the v2 gates. Returns ``(skill_or_None, reason)``."""
    skill = distill(trajectories, top_k=top_k)
    if skill is None:
        return None, "no successful trajectories"
    if int(skill.get("n_examples", 0)) < min_examples:
        return None, f"too few examples ({skill.get('n_examples', 0)} < {min_examples})"
    sig = _signature(skill)
    if is_duplicate(sig, existing_signatures or [], threshold=dedup_threshold):
        return None, "duplicate of an existing skill"
    return skill, "ok"


def distill_and_save_gated(trajectories: list[dict], *, store: Path | str = _STORE,
                           top_k: int = 3, min_examples: int = DEFAULT_MIN_EXAMPLES,
                           dedup_threshold: float = DEFAULT_DEDUP_THRESHOLD) -> tuple[Path | None, str]:
    """Gate + dedup against ``store``, save only a novel skill. Returns
    ``(path_or_None, reason)``."""
    existing = signatures_from_store(store)
    skill, reason = distill_gated(
        trajectories, existing_signatures=existing, top_k=top_k,
        min_examples=min_examples, dedup_threshold=dedup_threshold)
    if skill is None:
        return None, reason
    return save_skill(skill, store), "ok"


__all__ = ["distill_gated", "distill_and_save_gated", "is_duplicate",
           "signatures_from_store"]
