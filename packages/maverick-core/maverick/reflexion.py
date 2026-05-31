"""Reflexion library: per-failure self-critique persistence.

When an agent run fails, we want the NEXT similar run to remember
what went wrong and avoid the same mistake. This module is the
storage + retrieval layer for that loop.

Storage: ``~/.maverick/reflexions.ndjson`` (chmod 600), one JSON
object per line. Each entry records:
  - ts            — when the failure happened
  - goal_text     — title + description of the goal
  - failure_class — classified via maverick.retry_classifier
  - failure_msg   — the exception's short message
  - reflection    — the agent's own one-paragraph postmortem
  - tools_used    — list of tools the agent ran before failing

Retrieval: ``recall(goal_text, k=3)`` returns the top-K most similar
prior reflections. Used by the orchestrator's pre-run context layer
(opt-in via [reflexion] enable = true).

Similarity scoring: token-jaccard with simple normalization. We
intentionally don't depend on embeddings here; the vector_store
module is the right place for that and reflexions are usually
small enough that jaccard ranks them fine.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


DEFAULT_PATH = Path.home() / ".maverick" / "reflexions.ndjson"

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_lock = threading.Lock()


@dataclass
class Reflexion:
    ts: float
    goal_text: str
    failure_class: str
    failure_msg: str
    reflection: str
    tools_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _ensure_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def record(
    goal_text: str,
    failure_class: str,
    failure_msg: str,
    reflection: str,
    *,
    tools_used: list[str] | None = None,
    path: Path = DEFAULT_PATH,
) -> bool:
    """Append a Reflexion. Returns True on success.

    Fail-safe: write errors are logged and swallowed — a failed
    reflection write should never block a subsequent agent run.
    """
    entry = Reflexion(
        ts=time.time(),
        goal_text=goal_text or "",
        failure_class=failure_class or "unknown",
        failure_msg=failure_msg or "",
        reflection=reflection or "",
        tools_used=list(tools_used or []),
    )
    with _lock:
        try:
            _ensure_file(path)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), default=str) + "\n")
            return True
        except OSError as e:
            log.warning("reflexion: write failed: %s", e)
            return False


def _tokens(s: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(s or "")}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def recall(
    goal_text: str,
    *,
    k: int = 3,
    path: Path = DEFAULT_PATH,
    min_score: float = 0.05,
) -> list[tuple[float, Reflexion]]:
    """Return the top-k most similar prior reflections.

    Tuples are (score, Reflexion), sorted by score descending. Empty
    list if no file exists or no matches above ``min_score``.
    """
    if not goal_text or not path.exists():
        return []
    qt = _tokens(goal_text)
    scored: list[tuple[float, Reflexion]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                try:
                    entry = Reflexion(**{
                        k: data.get(k) for k in (
                            "ts", "goal_text", "failure_class",
                            "failure_msg", "reflection", "tools_used",
                        )
                    })
                except TypeError:
                    continue
                score = _jaccard(qt, _tokens(entry.goal_text))
                if score >= min_score:
                    scored.append((score, entry))
    except OSError:
        return []
    scored.sort(key=lambda p: p[0], reverse=True)
    return scored[:max(1, k)]


def list_recent(
    *,
    limit: int = 50,
    path: Path = DEFAULT_PATH,
) -> list[Reflexion]:
    """Return the N most recent reflexions, ordered newest-first."""
    if not path.exists():
        return []
    entries: list[Reflexion] = []
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                try:
                    entries.append(Reflexion(**{
                        k: data.get(k) for k in (
                            "ts", "goal_text", "failure_class",
                            "failure_msg", "reflection", "tools_used",
                        )
                    }))
                except TypeError:
                    continue
    except OSError:
        return []
    entries.sort(key=lambda r: r.ts, reverse=True)
    return entries[:max(1, limit)]


def clear(path: Path = DEFAULT_PATH) -> bool:
    """Delete the reflexion log."""
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def format_context(reflexions: list[tuple[float, Reflexion]]) -> str:
    """Render reflexions as a system-prompt addendum for the orchestrator."""
    if not reflexions:
        return ""
    lines = [
        "",
        "## Prior failures on similar goals",
        "",
        "You've encountered these failures before. Use them to avoid "
        "repeating the same mistake:",
        "",
    ]
    for score, r in reflexions:
        lines.append(
            f"- ({r.failure_class}, score {score:.2f}) {r.goal_text[:120]}"
        )
        if r.reflection:
            lines.append(f"  └─ lesson: {r.reflection[:300]}")
    lines.append("")
    return "\n".join(lines)


def enabled() -> bool:
    """Whether the cross-run reflexion learning loop is active.

    Off by default — the agent kernel must run without extra persisted
    state (CLAUDE.md rule 1 spirit). Turn it on with ``MAVERICK_REFLEXION=1``
    or ``[reflexion] enable = true`` in ``~/.maverick/config.toml``.
    """
    if os.environ.get("MAVERICK_REFLEXION", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return True
    try:
        from .config import load_config
        return bool(load_config().get("reflexion", {}).get("enable", False))
    except Exception:  # pragma: no cover -- config never blocks a run
        return False


def tools_from_blackboard(blackboard) -> list[str]:
    """Tool names a run invoked, parsed from the blackboard's observation
    posts (``tool=<name> -> ...``). Order-preserving + de-duplicated.
    Best-effort: any error yields an empty list.
    """
    seen: list[str] = []
    try:
        for e in getattr(blackboard, "entries", []) or []:
            if getattr(e, "kind", None) != "observation":
                continue
            m = re.match(r"tool=(\S+)", getattr(e, "content", "") or "")
            if m and m.group(1) not in seen:
                seen.append(m.group(1))
    except Exception:  # pragma: no cover
        pass
    return seen


def synthesize_reflection(
    failure_class: str, failure_msg: str, tools_used: list[str]
) -> str:
    """Build a one-paragraph postmortem WITHOUT an extra LLM call.

    The failure path may itself be budget-exhausted, so we synthesize a
    deterministic lesson from the classified failure + the tools the run
    actually reached for. Cheap, never raises, and good enough to steer
    the next similar run away from the same dead end.
    """
    tools = ", ".join(tools_used[:8]) if tools_used else "no tools"
    msg = (failure_msg or "").strip().splitlines()
    head = msg[0][:200] if msg else "(no message)"
    return (
        f"Previous attempt failed ({failure_class}): {head}. "
        f"Tools reached for: {tools}. "
        "Next time, plan the approach before spending budget, and verify "
        "the failing step in isolation before scaling it up."
    )


__all__ = [
    "Reflexion",
    "DEFAULT_PATH",
    "record",
    "recall",
    "list_recent",
    "clear",
    "format_context",
    "enabled",
    "tools_from_blackboard",
    "synthesize_reflection",
]
