"""Cost split by tag: aggregate run cost along an arbitrary tag dimension.

Groups priced runs by a tag (project / customer / label) and totals cost +
tokens per tag, so spend can be attributed instead of reported as one number.
``split_by_tag`` is a pure aggregation (unit-tested); ``gather`` adapts a world
model's episodes into its row format, reading the tag from episode/goal metadata
and bucketing anything untagged into ``(untagged)``.
"""
from __future__ import annotations

_UNTAGGED = "(untagged)"


def split_by_tag(rows: list[dict]) -> list[dict]:
    """Aggregate ``rows`` of ``{tag, cost, in_tok, out_tok}`` by tag.

    Returns ``{tag, cost, in_tok, out_tok, runs}`` per tag, highest cost first.
    Missing/blank tags fall into ``(untagged)``; non-numeric costs count as 0.
    """
    agg: dict[str, dict] = {}
    for row in rows or []:
        tag = str(row.get("tag") or "").strip() or _UNTAGGED
        bucket = agg.setdefault(
            tag, {"tag": tag, "cost": 0.0, "in_tok": 0, "out_tok": 0, "runs": 0})
        bucket["cost"] += _num(row.get("cost"))
        bucket["in_tok"] += int(_num(row.get("in_tok")))
        bucket["out_tok"] += int(_num(row.get("out_tok")))
        bucket["runs"] += 1
    out = list(agg.values())
    for b in out:
        b["cost"] = round(b["cost"], 6)
    out.sort(key=lambda b: -b["cost"])
    return out


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def gather(world, *, tag_field: str = "tag", limit: int = 500) -> list[dict]:
    """Build tag rows from a world model's priced episodes.

    Duck-typed: needs ``list_episodes(limit=...)`` yielding episodes with
    ``cost_dollars`` / ``in_tokens`` / ``out_tokens`` and an optional tag —
    looked up first on the episode, then on its goal's ``metadata``/``tags``.
    """
    rows: list[dict] = []
    goal_tags: dict[int, str] = {}
    for ep in world.list_episodes(limit=limit):
        cost = _num(getattr(ep, "cost_dollars", 0))
        if cost <= 0:
            continue
        tag = getattr(ep, tag_field, None)
        if not tag:
            gid = getattr(ep, "goal_id", None)
            if gid is not None and gid not in goal_tags:
                goal_tags[gid] = _goal_tag(world, gid, tag_field)
            tag = goal_tags.get(gid, "")
        rows.append({
            "tag": tag or "",
            "cost": cost,
            "in_tok": _num(getattr(ep, "in_tokens", 0)),
            "out_tok": _num(getattr(ep, "out_tokens", 0)),
        })
    return rows


def _goal_tag(world, gid: int, tag_field: str) -> str:
    try:
        g = world.get_goal(gid)
    except Exception:  # pragma: no cover -- missing goal
        return ""
    if g is None:
        return ""
    meta = getattr(g, "metadata", None)
    if isinstance(meta, dict):
        val = meta.get(tag_field) or meta.get("tag")
        if val:
            return str(val)
    tags = getattr(g, "tags", None)
    if tags:
        first = tags[0] if isinstance(tags, (list, tuple)) and tags else tags
        return str(first)
    return ""


def render(buckets: list[dict]) -> str:
    """Plain-text table for the CLI."""
    if not buckets:
        return "No priced runs to attribute yet."
    width = max(len(b["tag"]) for b in buckets)
    lines = [f"{'tag'.ljust(width)}   {'cost':>10}  {'runs':>5}  tokens"]
    for b in buckets:
        toks = b["in_tok"] + b["out_tok"]
        lines.append(
            f"{b['tag'].ljust(width)}   ${b['cost']:>9.4f}  {b['runs']:>5}  {toks}")
    return "\n".join(lines)


__all__ = ["split_by_tag", "gather", "render"]
