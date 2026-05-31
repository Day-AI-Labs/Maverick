"""Ingest donated trajectories into the training schema.

Reads ``~/.maverick/outbox/*.json`` (written by
``maverick.donation.write_record``) + the matching goal_events from
the world model, produces ``TrainingTrajectory`` objects, then writes
Klear-format JSONL for downstream training.

Usage:

    python -m maverick.training.ingest --in ~/.maverick/outbox \\
        --out trajectories.jsonl

Selection: only trajectories already on the gold list (the donation
selector gates on disagreement_high + outcome=success + verifier_conf
≥ 0.75) make it to the outbox in the first place. Ingest doesn't
re-filter; it labels.

Labels: HeuristicPRM labels per step (no human-in-loop needed). When
real labels are available (operator graded the run via thumbs / test
pass), those override the heuristic ones.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from pathlib import Path

from ..prm import HeuristicPRM, StepContext
from .schema import TrainingStep, TrainingTrajectory, to_klear_jsonl


def load_donations(outbox: Path) -> Iterator[dict]:
    """Yield each donated record (raw dict) from the outbox directory."""
    if not outbox.exists():
        return
    for p in sorted(outbox.glob("*.json")):
        try:
            yield json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue


def fetch_steps_for_goal(world, goal_id: int) -> list[dict]:
    """Pull goal_events for a goal from the world model.

    Returns dicts; the world is optional (donations may have been
    pruned before ingestion).
    """
    try:
        return [
            {"agent": e.agent, "kind": e.kind, "content": e.content, "ts": e.ts}
            for e in world.goal_events(goal_id)
        ]
    except Exception:
        return []


def build_trajectory(
    record: dict,
    events: list[dict],
    *,
    prm=None,
) -> TrainingTrajectory:
    """Convert a (donation record, goal_events) pair into a labeled
    TrainingTrajectory."""
    prm = prm or HeuristicPRM()
    steps: list[TrainingStep] = []
    prior_promise = 0.5
    for i, ev in enumerate(events):
        kind = ev.get("kind", "")
        action_type = {
            "plan": "think",
            "observation": "tool_call",
            "finding": "final",
            "verify": "think",
            "error": "tool_call",
        }.get(kind, "think")
        content = (ev.get("content") or "")[:200]
        error = content if kind == "error" else None
        tool_name = ""
        # observation lines come in as "tool=NAME -> ...".
        if kind == "observation" and content.startswith("tool="):
            tool_name = content.split(" ", 1)[0].split("=", 1)[1]
        is_final = kind == "finding"

        ctx = StepContext(
            goal_id=0, step_index=i, role=ev.get("agent", "").split("-")[0],
            tool_name=tool_name or None,
            tool_succeeded=(error is None) if action_type == "tool_call" else None,
            is_final=is_final, error=error,
            prior_step_score=prior_promise,
        )
        reward = prm.score(ctx)
        prior_promise = reward.promise

        # Hash the observation so we don't leak content into training.
        import hashlib
        obs_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

        steps.append(TrainingStep(
            step_index=i,
            role=ctx.role,
            action_type=action_type,
            action_name=tool_name,
            observation_hash=obs_hash,
            error=error,
            promise_label=reward.promise,
            progress_label=reward.progress,
        ))

    return TrainingTrajectory(
        trajectory_id=record.get("task_brief_hash", "") + "-"
                      + str(int(record.get("ts", 0))),
        task_brief_hash=record.get("task_brief_hash", ""),
        model_id=record.get("model_id", ""),
        outcome=record.get("outcome", ""),
        terminal_reward=record.get("reward", 0.0),
        verifier_confidence=record.get("verifier_confidence", 0.0),
        disagreement_entropy=record.get("disagreement_entropy", 0.0),
        wall_seconds=record.get("wall_seconds", 0.0),
        cost_dollars=record.get("cost_dollars", 0.0),
        steps=steps,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--in", dest="in_dir", type=Path,
        default=Path.home() / ".maverick" / "outbox",
        help="Donation outbox dir (default ~/.maverick/outbox)",
    )
    ap.add_argument(
        "--out", dest="out_file", type=Path,
        default=Path("trajectories.jsonl"),
        help="Output JSONL path (Klear format)",
    )
    args = ap.parse_args()

    try:
        from ..world_model import DEFAULT_DB, WorldModel
        world = WorldModel(DEFAULT_DB)
    except Exception:
        world = None

    count = 0
    with args.out_file.open("w", encoding="utf-8") as out:
        for record in load_donations(args.in_dir):
            events = (
                fetch_steps_for_goal(world, record.get("goal_id", 0))
                if world else []
            )
            traj = build_trajectory(record, events)
            out.write(json.dumps(to_klear_jsonl(traj)) + "\n")
            count += 1
    print(f"ingested {count} trajectories -> {args.out_file}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
