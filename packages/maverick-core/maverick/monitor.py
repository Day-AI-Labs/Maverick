"""Live plan/activity monitor for Maverick agents.

Reads the world model and renders a real-time view of:
  - the active goal (title, status, parent chain)
  - sub-goals (the plan tree)
  - recent events (tool calls, agent transitions, decisions)
  - cost and budget consumption
  - latest LLM activity

Designed to be reactive: the user starts an agent in one terminal, runs
`maverick monitor` in another, and watches the swarm work in real time.

This is the open-source equivalent of Devin's "watch over my shoulder"
UI -- without a paid VM. The plumbing is just the SQLite world model,
which agents write to as they progress.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .world_model import DEFAULT_DB, Goal, WorldModel

log = logging.getLogger(__name__)


# Single source of truth for goal/sub-goal status -> Rich color. Two separate
# inline maps used to drift: 'active' (the normal running state goals are set
# to via world_model.set_goal_status('active')) was in neither, so a live goal
# rendered uncolored; 'blocked' was missing from the plan-tree map. Centralize
# so the main status line and the plan tree can't disagree again.
# Keyed on the statuses the orchestrator actually writes
# (pending/active/blocked/done/cancelled) -- the old map also listed
# in_progress/running/succeeded/failed (never written) and lacked cancelled.
_STATUS_COLORS = {
    "pending": "yellow",
    "active": "cyan",
    "done": "green",
    "blocked": "red",
    "cancelled": "red",
}


def _status_color(status: str) -> str:
    return _STATUS_COLORS.get((status or "").lower(), "white")


@dataclass
class MonitorState:
    """Snapshot of one goal + its plan tree + recent activity."""
    goal: Goal
    children: list[Goal]
    recent_events: list  # list[GoalEvent]
    episodes: list  # list[EpisodeSpend]
    total_dollars: float

    @property
    def status_color(self) -> str:
        return _status_color(self.goal.status)


def _fetch_subgoals(world: WorldModel, parent_id: int) -> list[Goal]:
    """Return immediate children of a goal, sorted by created_at. Locked +
    backend-portable (was a raw world.conn.execute with `?` placeholders)."""
    return world.subgoals(parent_id, limit=50)


def _resolve_active_goal(world: WorldModel) -> Goal | None:
    """Pick the most-recently-touched in-flight goal as 'active'.

    Routes through the locked ``inflight_goal`` helper (vocab active/pending --
    what the orchestrator actually writes) instead of a raw query on the stale
    pending/in_progress/running set, which missed every `active` goal. Falls
    back to the most-recent goal regardless of status.
    """
    goal = world.inflight_goal()
    if goal is not None:
        return goal
    return world.most_recent_goal()


def snapshot(world: WorldModel, goal_id: int | None = None) -> MonitorState | None:
    """Read a complete monitor snapshot for ``goal_id`` (or active goal)."""
    if goal_id is None:
        goal = _resolve_active_goal(world)
        if goal is None:
            return None
    else:
        goal = world.get_goal(goal_id)
        if goal is None:
            return None
    children = _fetch_subgoals(world, goal.id)
    events = world.goal_events(goal.id, limit=40)
    # Show most-recent events at the bottom; trim to last 20.
    events = events[-20:]
    episodes = world.list_episodes(limit=10, goal_id=goal.id)
    totals = world.total_spend()
    return MonitorState(
        goal=goal,
        children=children,
        recent_events=events,
        episodes=episodes,
        total_dollars=float(totals.get("dollars") or 0.0),
    )


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


def _fmt_event(ev) -> str:
    """One-line summary for a GoalEvent."""
    age = time.time() - ev.ts
    return f"[dim]{_fmt_duration(age)} ago[/dim] [{ev.agent}] {ev.kind}: {(ev.content or '')[:120]}"


def render(state: MonitorState) -> str:
    """Render a MonitorState to a rich-formatted string.

    Returns plain text with rich-tag markup. Callers decide how to
    display (Console.print, file, websocket, etc).
    """
    parts: list[str] = []
    goal = state.goal
    age = time.time() - goal.created_at
    color = state.status_color
    parts.append(
        f"[bold]Goal #{goal.id}[/bold] [{color}]{goal.status}[/{color}]  "
        f"[dim]{_fmt_duration(age)} elapsed[/dim]"
    )
    parts.append(f"[bold]{goal.title}[/bold]")
    if goal.description:
        parts.append(f"[dim]{goal.description[:200]}[/dim]")
    parts.append("")

    if state.children:
        parts.append("[bold]Plan tree[/bold]")
        for c in state.children:
            cc = _status_color(c.status)
            parts.append(f"  ├─ [{cc}]{c.status:>11}[/{cc}]  #{c.id} {c.title[:80]}")
        parts.append("")

    if state.episodes:
        run = state.episodes[0]
        ended = run.ended_at and "done" or "running"
        parts.append(
            f"[bold]Latest episode #{run.id}[/bold] ({ended})  "
            f"${run.cost_dollars:.4f}  "
            f"in={run.input_tokens:,} out={run.output_tokens:,} "
            f"tools={run.tool_calls}"
        )
        parts.append("")

    if state.recent_events:
        parts.append("[bold]Recent activity[/bold]")
        for ev in state.recent_events:
            parts.append("  " + _fmt_event(ev))
        parts.append("")

    parts.append(
        f"[dim]Cumulative spend on this DB: ${state.total_dollars:.2f}[/dim]"
    )
    return "\n".join(parts)


def monitor_loop(
    db_path: Path = DEFAULT_DB,
    goal_id: int | None = None,
    interval_seconds: float = 1.5,
) -> int:
    """Run a live monitor in the terminal.

    Returns 0 when the user Ctrl-C's out. Returns 2 if no goal exists
    yet (db is empty).
    """
    try:
        from rich.console import Console
        from rich.live import Live
    except ImportError:
        return _monitor_loop_plain(db_path, goal_id, interval_seconds)

    console = Console()
    world = WorldModel(db_path)
    try:
        state = snapshot(world, goal_id)
        if state is None:
            console.print(
                f"[yellow]No goals found in {db_path}.[/yellow]\n"
                "Start one with: maverick start \"your task here\""
            )
            return 2
        with Live(render(state), console=console, refresh_per_second=2) as live:
            try:
                while True:
                    time.sleep(interval_seconds)
                    state = snapshot(world, goal_id)
                    if state is None:
                        live.update("[red]Goal not found.[/red]")
                        continue
                    live.update(render(state))
            except KeyboardInterrupt:
                pass
        return 0
    finally:
        world.close()


def _monitor_loop_plain(db_path: Path, goal_id: int | None, interval: float) -> int:
    """Fallback when rich isn't installed: print snapshot every N seconds.

    Less pretty but works in any terminal. ANSI escape codes for clear.
    """
    import sys

    world = WorldModel(db_path)
    try:
        try:
            while True:
                state = snapshot(world, goal_id)
                # Clear screen + home cursor.
                sys.stdout.write("\033[2J\033[H")
                if state is None:
                    sys.stdout.write(
                        f"No goals found in {db_path}.\n"
                        "Start one with: maverick start \"your task here\"\n"
                    )
                else:
                    # Strip rich tags for plain output.
                    import re
                    plain = re.sub(r"\[/?[a-z #]+\]", "", render(state))
                    sys.stdout.write(plain + "\n")
                sys.stdout.flush()
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        world.close()
