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
from typing import Optional

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
    tools_used: Optional[list[str]] = None,
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


__all__ = [
    "Reflexion",
    "DEFAULT_PATH",
    "record",
    "recall",
    "list_recent",
    "clear",
    "format_context",
]
