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
import time
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
            scoped = _scoped_key(goal_id, user_key)
            # Upsert: delete existing for this scoped key, insert.
            world.conn.execute("DELETE FROM facts WHERE key=?", (scoped,))
            world.conn.execute(
                "INSERT INTO facts(key, value, updated_at) VALUES(?, ?, ?)",
                (scoped, value, time.time()),
            )
            world.conn.commit()
            return f"set {user_key!r} ({len(value)} bytes)"
        if op == "get":
            user_key = (args.get("key") or "").strip()
            if not user_key:
                return "ERROR: get requires key"
            row = world.conn.execute(
                "SELECT value FROM facts WHERE key=? LIMIT 1",
                (_scoped_key(goal_id, user_key),),
            ).fetchone()
            if row is None:
                return f"(no fact stored for {user_key!r})"
            return row["value"]
        if op == "delete":
            user_key = (args.get("key") or "").strip()
            if not user_key:
                return "ERROR: delete requires key"
            cur = world.conn.execute(
                "DELETE FROM facts WHERE key=?",
                (_scoped_key(goal_id, user_key),),
            )
            world.conn.commit()
            return f"deleted {cur.rowcount} row(s)"
        prefix_like = f"goal:{goal_id}:%"
        if op == "list":
            rows = world.conn.execute(
                "SELECT key, length(value) AS sz FROM facts "
                "WHERE key LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (prefix_like, cap),
            ).fetchall()
            if not rows:
                return "(no facts stored for this goal)"
            return "\n".join(f"{_unscope(r['key'])}  ({r['sz']} bytes)" for r in rows)
        if op == "search":
            q = (args.get("query") or "").strip()
            if not q:
                return "ERROR: search requires query"
            like = f"%{q}%"
            rows = world.conn.execute(
                "SELECT key, value FROM facts WHERE key LIKE ? "
                "AND (key LIKE ? OR value LIKE ?) "
                "ORDER BY updated_at DESC LIMIT ?",
                (prefix_like, like, like, cap),
            ).fetchall()
            if not rows:
                return f"no matches for {q!r}"
            out = []
            for r in rows:
                snippet = (r["value"] or "")[:200]
                out.append(f"{_unscope(r['key'])}: {snippet}")
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
