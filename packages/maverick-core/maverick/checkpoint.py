"""Durable execution — Phase 1: linear single-agent crash-resume.

Design: ``docs/specs/durable-execution.md``. This is the smallest shippable
slice of that spec — checkpoint a single (non-spawning) agent's loop state at
the turn boundary and resume it from the last committed step after a crash,
instead of re-running from step 0 (today's warm-restart behavior).

Scope of Phase 1 (intentionally narrow):
  - One agent (the orchestrator / a depth-0 agent that doesn't fan out). The
    swarm-tree case (spawn_swarm concurrency, per-child records) is Phase 2.
  - Checkpoints the resumable loop state: step index, the LLM ``messages``
    history, and a Budget snapshot (spent counters).
  - Append-only ``checkpoints`` table keyed by (goal_id, episode_id, agent_id, step_seq),
    in its OWN table so it needs no world-model schema-version migration.

Posture (kernel rule 1): OFF by default, fail-open. ``enabled()`` gates the
whole feature; every read/write is wrapped so a checkpoint-store error
degrades to today's warm-restart, never aborts a run.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS checkpoints (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id     INTEGER NOT NULL,
    episode_id  INTEGER NOT NULL DEFAULT 0,
    agent_id    TEXT NOT NULL,
    step_seq    INTEGER NOT NULL,
    created_at  REAL NOT NULL,
    -- JSON blobs: the resumable loop state.
    messages    TEXT NOT NULL,
    budget      TEXT NOT NULL,
    meta        TEXT NOT NULL DEFAULT '{}'
)
"""
# The lookup key is (goal_id, episode_id, agent_id): episode_id discriminates
# best-of-N attempts (each attempt is a fresh episode under one goal_id), so a
# resumed attempt never picks up a sibling attempt's checkpoint. agent_id is a
# STABLE id (e.g. "orchestrator-0"), not the per-process random Agent.name.
_CREATE_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_checkpoints_lookup "
    "ON checkpoints(goal_id, episode_id, agent_id, step_seq DESC)"
)


def enabled() -> bool:
    """Whether durable checkpointing is active. Off by default.

    Mirrors the ``self_learning.enabled()`` opt-in pattern: env first, then
    ``[durable] enabled`` config, then False. Config never blocks a run.
    """
    env = os.environ.get("MAVERICK_DURABLE", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    try:
        from .config import get_durable
        return bool(get_durable()["enabled"])
    except Exception:  # pragma: no cover -- config never blocks a run
        return False


def _keep_last() -> int:
    """How many checkpoints to retain per (goal, agent) for rewind/history."""
    try:
        from .config import get_durable
        return int(get_durable()["keep_last"])
    except Exception:
        return 5


@dataclass
class Checkpoint:
    goal_id: int
    episode_id: int
    agent_id: str
    step_seq: int
    messages: list[dict]
    budget: dict
    meta: dict


class Checkpointer:
    """Append-only checkpoint store over the world model's SQLite connection.

    Owns its own ``checkpoints`` table (created lazily), so it does not touch
    the world-model schema version. All methods fail open: a DB error logs and
    returns a safe default rather than raising into the agent loop.
    """

    def __init__(self, world: Any):
        self._world = world
        self._ready = False

    def _ensure(self) -> bool:
        if self._ready:
            return True
        try:
            with self._world._writing() as conn:
                conn.execute(_CREATE_TABLE)
                conn.execute(_CREATE_INDEX)
            self._ready = True
        except Exception as e:  # pragma: no cover -- never block a run
            log.warning("checkpoint: table init failed (disabling): %s", e)
        return self._ready

    def save(
        self,
        *,
        goal_id: int,
        agent_id: str,
        step_seq: int,
        messages: list[dict],
        budget: Any,
        episode_id: int = 0,
        meta: dict | None = None,
    ) -> bool:
        """Commit a checkpoint at the turn boundary. Returns True on success."""
        if goal_id is None or not self._ensure():
            return False
        try:
            payload_messages = json.dumps(messages, default=str)
            payload_budget = json.dumps(snapshot_budget(budget))
            payload_meta = json.dumps(meta or {}, default=str)
        except (TypeError, ValueError) as e:  # non-serializable -> skip, don't crash
            log.debug("checkpoint: payload not serializable, skipping: %s", e)
            return False
        try:
            with self._world._writing() as conn:
                conn.execute(
                    "INSERT INTO checkpoints"
                    "(goal_id, episode_id, agent_id, step_seq, created_at, "
                    " messages, budget, meta) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                    (goal_id, episode_id, agent_id, step_seq, time.time(),
                     payload_messages, payload_budget, payload_meta),
                )
            self._prune(goal_id, episode_id, agent_id)
            return True
        except Exception as e:  # pragma: no cover -- never block a run
            log.warning("checkpoint: save failed (continuing uncheckpointed): %s", e)
            return False

    def latest_episode_id(self, goal_id: int, agent_id: str) -> int | None:
        """Return the episode containing the newest checkpoint for (goal, agent)."""
        if goal_id is None or not self._ensure():
            return None
        try:
            row = self._world.conn.execute(
                "SELECT episode_id FROM checkpoints "
                "WHERE goal_id = ? AND agent_id = ? "
                "ORDER BY created_at DESC, step_seq DESC, id DESC LIMIT 1",
                (goal_id, agent_id),
            ).fetchone()
        except Exception as e:  # pragma: no cover
            log.warning("checkpoint: latest_episode_id() failed: %s", e)
            return None
        if row is None:
            return None
        return int(row[0])

    def latest(self, goal_id: int, agent_id: str, episode_id: int = 0) -> Checkpoint | None:
        """Return the most recent checkpoint for (goal, episode, agent), or None."""
        if goal_id is None or not self._ensure():
            return None
        try:
            row = self._world.conn.execute(
                "SELECT goal_id, episode_id, agent_id, step_seq, messages, budget, meta "
                "FROM checkpoints WHERE goal_id = ? AND episode_id = ? AND agent_id = ? "
                "ORDER BY step_seq DESC LIMIT 1",
                (goal_id, episode_id, agent_id),
            ).fetchone()
        except Exception as e:  # pragma: no cover
            log.warning("checkpoint: latest() failed: %s", e)
            return None
        if row is None:
            return None
        try:
            return Checkpoint(
                goal_id=row[0], episode_id=row[1], agent_id=row[2], step_seq=row[3],
                messages=json.loads(row[4]), budget=json.loads(row[5]),
                meta=json.loads(row[6]),
            )
        except (TypeError, ValueError) as e:
            log.warning("checkpoint: corrupt record for goal=%s ep=%s agent=%s: %s",
                        goal_id, episode_id, agent_id, e)
            return None

    def _prune(self, goal_id: int, episode_id: int, agent_id: str) -> None:
        keep = _keep_last()
        try:
            with self._world._writing() as conn:
                conn.execute(
                    "DELETE FROM checkpoints "
                    "WHERE goal_id = ? AND episode_id = ? AND agent_id = ? "
                    "AND id NOT IN ("
                    "  SELECT id FROM checkpoints "
                    "  WHERE goal_id = ? AND episode_id = ? AND agent_id = ? "
                    "  ORDER BY step_seq DESC LIMIT ?"
                    ")",
                    (goal_id, episode_id, agent_id,
                     goal_id, episode_id, agent_id, keep),
                )
        except Exception as e:  # pragma: no cover
            log.debug("checkpoint: prune failed (non-fatal): %s", e)

    def clear(self, goal_id: int) -> None:
        """Drop all checkpoints for a goal (call on successful completion)."""
        if goal_id is None or not self._ensure():
            return
        try:
            with self._world._writing() as conn:
                conn.execute("DELETE FROM checkpoints WHERE goal_id = ?", (goal_id,))
        except Exception as e:  # pragma: no cover
            log.debug("checkpoint: clear failed (non-fatal): %s", e)

    # ----- rewind / fork support (spec §4, G2) -----

    def orchestrator_for(self, goal_id: int) -> tuple[str, int] | None:
        """``(agent_id, episode_id)`` of the goal's newest checkpoint.

        Phase 1 only checkpoints the depth-0 root, so the newest checkpoint's
        agent is the orchestrator — the node ``rewind`` operates on."""
        if goal_id is None or not self._ensure():
            return None
        try:
            row = self._world.conn.execute(
                "SELECT agent_id, episode_id FROM checkpoints WHERE goal_id = ? "
                "ORDER BY created_at DESC, step_seq DESC, id DESC LIMIT 1",
                (goal_id,),
            ).fetchone()
        except Exception as e:  # pragma: no cover
            log.warning("checkpoint: orchestrator_for() failed: %s", e)
            return None
        return (str(row[0]), int(row[1])) if row else None

    def list_steps(self, goal_id: int, agent_id: str, episode_id: int = 0) -> list[int]:
        """Checkpoint step indices (ascending) kept for (goal, episode, agent)."""
        if goal_id is None or not self._ensure():
            return []
        try:
            rows = self._world.conn.execute(
                "SELECT step_seq FROM checkpoints "
                "WHERE goal_id = ? AND episode_id = ? AND agent_id = ? "
                "ORDER BY step_seq ASC",
                (goal_id, episode_id, agent_id),
            ).fetchall()
        except Exception as e:  # pragma: no cover
            log.warning("checkpoint: list_steps() failed: %s", e)
            return []
        return [int(r[0]) for r in rows]

    def at_or_before_step(self, goal_id: int, agent_id: str, step_seq: int,
                          episode_id: int = 0) -> Checkpoint | None:
        """The newest checkpoint at or before ``step_seq`` (the rewind target)."""
        if goal_id is None or not self._ensure():
            return None
        try:
            row = self._world.conn.execute(
                "SELECT goal_id, episode_id, agent_id, step_seq, messages, budget, meta "
                "FROM checkpoints WHERE goal_id = ? AND episode_id = ? AND agent_id = ? "
                "AND step_seq <= ? ORDER BY step_seq DESC LIMIT 1",
                (goal_id, episode_id, agent_id, step_seq),
            ).fetchone()
        except Exception as e:  # pragma: no cover
            log.warning("checkpoint: at_or_before_step() failed: %s", e)
            return None
        if row is None:
            return None
        try:
            return Checkpoint(
                goal_id=row[0], episode_id=row[1], agent_id=row[2], step_seq=row[3],
                messages=json.loads(row[4]), budget=json.loads(row[5]),
                meta=json.loads(row[6]),
            )
        except (TypeError, ValueError):  # pragma: no cover -- corrupt row
            return None

    def truncate_after(self, goal_id: int, agent_id: str, step_seq: int,
                       episode_id: int = 0) -> int:
        """Delete checkpoints AFTER ``step_seq`` so the next resume continues
        from it. Returns the number removed."""
        if goal_id is None or not self._ensure():
            return 0
        try:
            with self._world._writing() as conn:
                cur = conn.execute(
                    "DELETE FROM checkpoints WHERE goal_id = ? AND episode_id = ? "
                    "AND agent_id = ? AND step_seq > ?",
                    (goal_id, episode_id, agent_id, step_seq),
                )
                return int(cur.rowcount or 0)
        except Exception as e:  # pragma: no cover
            log.warning("checkpoint: truncate_after() failed: %s", e)
            return 0

    def copy_checkpoint(self, ckpt: Checkpoint, dst_goal_id: int) -> bool:
        """Write ``ckpt`` under a different goal id (for ``--fork``). Keeps the
        same episode/agent/step so the forked goal's resume finds it unchanged."""
        if dst_goal_id is None or not self._ensure():
            return False
        try:
            with self._world._writing() as conn:
                conn.execute(
                    "INSERT INTO checkpoints"
                    "(goal_id, episode_id, agent_id, step_seq, created_at, "
                    " messages, budget, meta) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                    (dst_goal_id, ckpt.episode_id, ckpt.agent_id, ckpt.step_seq,
                     time.time(), json.dumps(ckpt.messages, default=str),
                     json.dumps(ckpt.budget), json.dumps(ckpt.meta, default=str)),
                )
            return True
        except Exception as e:  # pragma: no cover
            log.warning("checkpoint: copy_checkpoint() failed: %s", e)
            return False


@dataclass
class RewindResult:
    ok: bool
    detail: str
    target_step: int | None = None
    forked_goal_id: int | None = None


def rewind(world: Any, goal_id: int, to_step: int, *, fork: bool = False) -> RewindResult:
    """Restart a goal from an earlier checkpoint (spec §4, G2).

    Without ``fork``: drop the checkpoints after ``to_step`` and re-block the
    goal so ``maverick resume`` continues from there. With ``fork``: copy the
    target checkpoint under a NEW child goal (same department, so the resumed
    role keys the same ``checkpoint_id``), leaving the original intact — "go back
    to step N and try a different branch."

    Builds only on the shipped Phase-1 per-step checkpoints (no swarm-tree
    concurrency). Never raises; returns a structured result.
    """
    ck = Checkpointer(world)
    found = ck.orchestrator_for(goal_id)
    if found is None:
        return RewindResult(False, f"goal #{goal_id} has no checkpoints "
                            "(durable execution off, or a legacy/never-run goal)")
    agent_id, episode_id = found
    target = ck.at_or_before_step(goal_id, agent_id, to_step, episode_id)
    if target is None:
        steps = ck.list_steps(goal_id, agent_id, episode_id)
        return RewindResult(False, f"no checkpoint at or before step {to_step} "
                            f"for goal #{goal_id} (available steps: {steps})")
    if fork:
        g = world.get_goal(goal_id)
        title = getattr(g, "title", None) or f"rewind of #{goal_id}"
        desc = getattr(g, "description", "") or ""
        domain = getattr(g, "domain", "") or ""
        new_goal = world.create_goal(title, desc, parent_id=goal_id, domain=domain)
        if not ck.copy_checkpoint(target, new_goal):
            return RewindResult(False, "fork failed: could not copy the checkpoint")
        try:
            world.set_goal_status(new_goal, "blocked")
        except Exception:  # pragma: no cover -- best effort
            pass
        return RewindResult(
            True,
            f"forked goal #{goal_id} -> new goal #{new_goal} at step {target.step_seq}; "
            f"resume it with `maverick resume {new_goal}`",
            target_step=target.step_seq, forked_goal_id=new_goal)
    removed = ck.truncate_after(goal_id, agent_id, target.step_seq, episode_id)
    try:
        world.set_goal_status(goal_id, "blocked")
    except Exception:  # pragma: no cover -- best effort
        pass
    return RewindResult(
        True,
        f"rewound goal #{goal_id} to step {target.step_seq} "
        f"({removed} later checkpoint(s) dropped); continue with "
        f"`maverick resume {goal_id}`",
        target_step=target.step_seq)


# ----- Budget (de)serialization -----
# Budget is a dataclass of plain int/float counters + caps; snapshot the
# resumable fields and restore them onto a fresh Budget so spent accounting
# survives a resume. Wall-clock is restored by back-dating started_at so
# elapsed() continues from where it left off rather than resetting to 0.

_BUDGET_COUNTERS = (
    "input_tokens", "output_tokens", "cache_read_tokens",
    "cache_write_tokens", "dollars", "tool_calls",
)
_BUDGET_CAPS = (
    "max_input_tokens", "max_output_tokens", "max_dollars",
    "max_wall_seconds", "max_tool_calls",
)


def snapshot_budget(budget: Any) -> dict:
    """Serialize a Budget's caps + spent counters + elapsed wall time."""
    out: dict = {}
    for f in (*_BUDGET_CAPS, *_BUDGET_COUNTERS):
        out[f] = getattr(budget, f, None)
    try:
        out["_elapsed"] = budget.elapsed()
    except Exception:
        out["_elapsed"] = 0.0
    return out


def restore_budget(snapshot: dict):
    """Rebuild a Budget from a snapshot, preserving spent counters + elapsed."""
    from .budget import Budget
    kwargs = {f: snapshot[f] for f in _BUDGET_CAPS if snapshot.get(f) is not None}
    b = Budget(**kwargs)
    for f in _BUDGET_COUNTERS:
        if snapshot.get(f) is not None:
            setattr(b, f, snapshot[f])
    # Restore the wall-clock baseline so elapsed() continues from the saved
    # value. Budget.elapsed() reads `_started_monotonic` (set unconditionally in
    # __post_init__), NOT `started_at`, so back-dating started_at alone was a
    # dead write that reset the wall cap to ~0 on every resume -- a budget-cap
    # bypass on the durable-execution path. Back-date the monotonic baseline the
    # way Budget.__setstate__ already does.
    elapsed = snapshot.get("_elapsed") or 0.0
    try:
        b._started_monotonic = time.monotonic() - max(0.0, float(elapsed))
        b.started_at = time.time() - float(elapsed)  # keep legacy field consistent
    except Exception:
        pass
    return b


__all__ = [
    "enabled", "Checkpoint", "Checkpointer", "RewindResult", "rewind",
    "snapshot_budget", "restore_budget",
]
