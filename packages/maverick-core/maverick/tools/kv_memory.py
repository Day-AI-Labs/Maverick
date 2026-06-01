"""Per-goal key/value memory tool.

Lets long-running agents persist facts across turns without bloating
the conversation. Backed by the world_model's ``facts`` table (already
exists). Three ops:

  - kv_set(key, value)  — write (overwrites if key already exists for goal)
  - kv_get(key)         — read; returns missing-sentinel if absent
  - kv_search(query)    — substring search across keys/values for the goal

Scoped to the current goal so memory doesn't leak across runs. Use the
``recall_past_goals`` tool when you need cross-goal context.
"""
from __future__ import annotations

import logging
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_KV_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["set", "get", "search", "delete", "list"],
            "description": "Operation.",
        },
        "key": {"type": "string", "description": "Fact key (for set/get/delete)."},
        "value": {"type": "string", "description": "Fact value (for set)."},
        "query": {"type": "string", "description": "Substring (for search)."},
        "max_results": {"type": "integer", "description": "Cap for search/list (default 50)."},
    },
    "required": ["op"],
}


def _scoped_key(goal_id: int, user_key: str) -> str:
    """Prefix the key so kv_memory is goal-scoped on the flat ``facts`` table."""
    return f"goal:{goal_id}:{user_key}"


def _unscope(scoped_key: str) -> str:
    """Strip the ``goal:N:`` prefix; returns the original user-supplied key."""
    parts = scoped_key.split(":", 2)
    if len(parts) == 3 and parts[0] == "goal":
        return parts[2]
    return scoped_key


def _run_factory(world, goal_id: int | None):
    def _run(args: dict[str, Any]) -> str:
        if world is None or goal_id is None:
            return "ERROR: kv_memory requires an active goal (world / goal_id missing)"
        op = args.get("op")
        if not op:
            return "ERROR: op is required"
        cap = max(1, min(int(args.get("max_results") or 50), 500))
        if op == "set":
            user_key = (args.get("key") or "").strip()
            value = args.get("value") or ""
            if not user_key:
                return "ERROR: set requires key"
            # Cap the value: an unbounded write lets the agent stash hundreds
            # of MB in SQLite that a later get() floods the context window
            # with. 64 KB is plenty for a fact; store a summary or path else.
            if len(value) > 65536:
                return (
                    f"ERROR: value too large ({len(value)} chars; max 65536). "
                    "Store a summary or a file path instead."
                )
            scoped = _scoped_key(goal_id, user_key)
            # Locked upsert via the WorldModel helper (#470): no longer
            # reaches into conn.execute (torn writes under the threadpool /
            # `?` breaks the psycopg backend).
            world.set_fact_raw(scoped, value)
            return f"set {user_key!r} ({len(value)} bytes)"
        if op == "get":
            user_key = (args.get("key") or "").strip()
            if not user_key:
                return "ERROR: get requires key"
            value = world.get_fact(_scoped_key(goal_id, user_key))
            if value is None:
                return f"(no fact stored for {user_key!r})"
            return value
        if op == "delete":
            user_key = (args.get("key") or "").strip()
            if not user_key:
                return "ERROR: delete requires key"
            removed = world.delete_fact(_scoped_key(goal_id, user_key))
            return f"deleted {removed} row(s)"
        prefix_like = f"goal:{goal_id}:%"
        if op == "list":
            rows = world.list_facts(prefix_like, limit=cap)
            if not rows:
                return "(no facts stored for this goal)"
            return "\n".join(f"{_unscope(k)}  ({sz} bytes)" for k, sz in rows)
        if op == "search":
            q = (args.get("query") or "").strip()
            if not q:
                return "ERROR: search requires query"
            like = f"%{q}%"
            rows = world.search_facts(prefix_like, like, limit=cap)
            if not rows:
                return f"no matches for {q!r}"
            out = []
            for k, v in rows:
                snippet = (v or "")[:200]
                out.append(f"{_unscope(k)}: {snippet}")
            return "\n".join(out)
        return f"ERROR: unknown op {op!r}"
    return _run


def kv_memory(world, goal_id: int | None) -> Tool:
    """Factory: builds the kv_memory tool bound to (world, goal_id)."""
    return Tool(
        name="kv_memory",
        description=(
            "Persist facts across turns for the current goal. ops: "
            "set (upsert), get (read), delete, list (recent keys), "
            "search (substring across keys+values). Goal-scoped -- "
            "memory doesn't leak across runs. Use recall_past_goals "
            "for cross-goal context."
        ),
        input_schema=_KV_SCHEMA,
        fn=_run_factory(world, goal_id),
    )
