"""Local achievements (roadmap: 2028 H2 UX).

A small, local-only milestone ledger: achievements are *derived from the
world model's recorded history* (never self-reported, nothing leaves the
machine) and unlock exactly once. The catalog rewards the behaviors the
product actually cares about — finishing long-horizon work, using budgets,
reviewing approvals — not engagement-bait streaks.

``evaluate(world)`` checks every rule against history and persists newly
unlocked achievements to ``data_dir("achievements.json")`` (atomic, 0600)
with the unlock timestamp; ``unlocked()`` lists them. Off the hot path —
the dashboard/CLI call it on view, nothing runs per-turn.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Achievement:
    key: str
    title: str
    description: str
    check: Callable  # (stats: dict) -> bool


def _stats(world) -> dict:
    """The cheap aggregate the rules read (one pass over goals)."""
    out = {"goals_total": 0, "goals_done": 0, "max_subgoals": 0,
           "channels": set(), "approvals_decided": 0}
    try:
        goals = world.list_goals(limit=100_000)
    except Exception:
        goals = []
    by_parent: dict = {}
    for g in goals:
        out["goals_total"] += 1
        if getattr(g, "status", "") in ("done", "succeeded", "completed"):
            out["goals_done"] += 1
        parent = getattr(g, "parent_id", None)
        if parent is not None:
            by_parent[parent] = by_parent.get(parent, 0) + 1
    out["max_subgoals"] = max(by_parent.values(), default=0)
    try:
        out["channels"] = {getattr(c, "channel", "?")
                           for c in world.list_conversations()}
    except Exception:
        out["channels"] = set()
    try:
        out["approvals_decided"] = sum(
            1 for a in world.list_approvals(limit=100_000)
            if (getattr(a, "status", "") or "").lower() in ("approved", "denied"))
    except Exception:
        pass
    return out


CATALOG: tuple[Achievement, ...] = (
    Achievement("first_goal", "First flight",
                "Completed your first goal.",
                lambda s: s["goals_done"] >= 1),
    Achievement("ten_goals", "Operator",
                "Completed 10 goals.",
                lambda s: s["goals_done"] >= 10),
    Achievement("hundred_goals", "Fleet commander",
                "Completed 100 goals.",
                lambda s: s["goals_done"] >= 100),
    Achievement("deep_swarm", "Swarm conductor",
                "One goal fanned out into 5+ sub-goals.",
                lambda s: s["max_subgoals"] >= 5),
    Achievement("multichannel", "Everywhere at once",
                "Drove Maverick from 3+ different channels.",
                lambda s: len(s["channels"]) >= 3),
    Achievement("reviewer", "Human in the loop",
                "Decided 10 approval requests.",
                lambda s: s["approvals_decided"] >= 10),
)


def _store_path() -> Path:
    from .paths import data_dir
    return data_dir("achievements.json")


def unlocked(path: Path | None = None) -> dict[str, float]:
    """``{key: unlocked_at}`` for everything earned so far."""
    p = path or _store_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in raw.items()}
    except (OSError, ValueError):
        return {}


def evaluate(world, *, path: Path | None = None,
             now: float | None = None) -> list[Achievement]:
    """Check the catalog against history; persist + return NEW unlocks."""
    p = path or _store_path()
    earned = unlocked(p)
    stats = _stats(world)
    fresh: list[Achievement] = []
    for ach in CATALOG:
        if ach.key in earned:
            continue
        try:
            if ach.check(stats):
                fresh.append(ach)
        except Exception:  # a rule error must never break the view
            continue
    if fresh:
        ts = float(now if now is not None else time.time())
        # Reload the earned set under a cross-process lock before applying this
        # run's unlocks: two concurrent evaluate()s would otherwise both load
        # the old set and the second save would drop the first's unlocks.
        # Re-stamping a key another process already unlocked is idempotent.
        from .file_lock import atomic_write_text, cross_process_lock
        with cross_process_lock(p):
            earned = unlocked(p)
            for ach in fresh:
                earned[ach.key] = ts
            atomic_write_text(p, json.dumps(earned, sort_keys=True))
    return fresh


def render(world, *, path: Path | None = None) -> str:
    evaluate(world, path=path)
    earned = unlocked(path)
    lines = [f"achievements: {len(earned)}/{len(CATALOG)} unlocked"]
    for ach in CATALOG:
        mark = "★" if ach.key in earned else "·"
        lines.append(f"  {mark} {ach.title} — {ach.description}")
    return "\n".join(lines)


__all__ = ["Achievement", "CATALOG", "evaluate", "unlocked", "render"]
