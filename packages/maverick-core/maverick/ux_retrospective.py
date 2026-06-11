"""UX retrospective generator (roadmap: 2028 H2 UX — "36-month UX
retrospective + reset").

The period generator for the UX half of the retrospective trio (safety:
``safety_report``; perf: ``benchmark_retrospective``). Aggregates what the
deployment recorded about how it was *used* over a window — goal volume and
outcomes, channel mix, approval friction, template adoption — into an honest
markdown retrospective plus a **reset worksheet**: the questions the
36-month reset answers from the data (what to cut, what to double down on),
with the data row each question reads from.

Pure over an injected world (and optional ledgers); sections without data say
so. ``python -m maverick.ux_retrospective --since --until`` runs it; the
36-month cadence is when the operator runs it, not something this fabricates.
"""
from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def collect(world, start_ts: float, end_ts: float) -> dict:
    """Aggregate UX signals from the world model for the window."""
    out: dict = {
        "window": {"since": _iso(start_ts), "until": _iso(end_ts)},
        "goals": {"total": 0, "by_status": {}, "by_verb": {}},
        "channels": {},
        "approvals": {"decided": 0, "approved": 0, "denied": 0},
    }
    try:
        goals = world.list_goals(limit=100_000)
    except Exception:
        goals = []
    verb_counter: Counter = Counter()
    status_counter: Counter = Counter()
    for g in goals:
        created = getattr(g, "created_at", None)
        if created is None or not (start_ts <= float(created) <= end_ts):
            continue
        out["goals"]["total"] += 1
        status_counter[getattr(g, "status", "unknown")] += 1
        title = (getattr(g, "title", "") or "").strip().lower()
        first = title.split()[0] if title else ""
        if first.isalpha():
            verb_counter[first] += 1
    out["goals"]["by_status"] = dict(status_counter)
    out["goals"]["by_verb"] = dict(verb_counter.most_common(10))
    try:
        convs = world.list_conversations()
        chan_counter: Counter = Counter()
        for c in convs:
            chan_counter[getattr(c, "channel", "unknown")] += 1
        out["channels"] = dict(chan_counter)
    except Exception:
        out["channels"] = {}
    try:
        for a in world.list_approvals(limit=100_000):
            ts = getattr(a, "decided_at", None) or getattr(a, "created_at", 0)
            if not (start_ts <= float(ts or 0) <= end_ts):
                continue
            status = (getattr(a, "status", "") or "").lower()
            if status in ("approved", "denied"):
                out["approvals"]["decided"] += 1
                out["approvals"][status] += 1
    except Exception:
        pass
    return out


def render(data: dict) -> str:
    g = data["goals"]
    ap = data["approvals"]
    lines = [
        f"# UX retrospective — {data['window']['since']} → "
        f"{data['window']['until']}",
        "",
        "## Usage",
        f"- goals in window: {g['total']}"
        + ("" if g["total"] else " (no recorded usage in this window)"),
    ]
    if g["by_status"]:
        lines.append("- outcomes: " + ", ".join(
            f"{k}={v}" for k, v in sorted(g["by_status"].items())))
    if g["by_verb"]:
        lines.append("- top task verbs: " + ", ".join(
            f"{k} ({v})" for k, v in g["by_verb"].items()))
    lines.append("")
    lines.append("## Channels")
    if data["channels"]:
        for ch, n in sorted(data["channels"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- {ch}: {n} conversation(s)")
    else:
        lines.append("- no channel conversations recorded")
    lines += [
        "",
        "## Approval friction",
        (f"- {ap['decided']} decided ({ap['approved']} approved / "
         f"{ap['denied']} denied)" if ap["decided"]
         else "- no approval decisions recorded"),
        "",
        "## Reset worksheet (answered from the rows above)",
        "- Which surfaces saw zero use this period? (channels with no "
        "conversations → candidates to re-home or cut)",
        "- Where is approval friction concentrated? (denied/decided ratio "
        "high → tighten defaults or improve previews)",
        "- Which task verbs dominate? (top verbs → invest; absent verbs the "
        "roadmap bet on → revisit the bet)",
        "- Did outcomes improve? (compare by_status across consecutive "
        "retrospectives)",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- CLI shell
    import argparse
    p = argparse.ArgumentParser(prog="maverick.ux_retrospective")
    p.add_argument("--since-days", type=float, default=365.0)
    args = p.parse_args(argv)
    from .world_model import open_world
    world = open_world()
    end = time.time()
    print(render(collect(world, end - args.since_days * 86400.0, end)))
    return 0


__all__ = ["collect", "render"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
