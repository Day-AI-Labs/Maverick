"""SQL query tool — read-only by default, over a local SQLite database.

Lets the agent inspect a SQLite file with real SQL. Read-only is the
default and is enforced at the engine level (the connection is opened
``mode=ro``), so a SELECT can never mutate the database even if a write
slips past the keyword guard. Set ``read_only=false`` to allow writes.

SQLite only for v1 (stdlib, no dependency, and it's the same engine the
world model uses). The DB path is confined to the sandbox workspace.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from . import Tool
from .ffmpeg_tool import _safe_path

log = logging.getLogger(__name__)

_MAX_ROWS_CAP = 1000
_MAX_OUTPUT = 50_000
_WRITE_KEYWORDS = frozenset({
    "insert", "update", "delete", "replace", "drop", "alter", "create",
    "truncate", "attach", "detach", "reindex", "vacuum",
})


_SQL_QUERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "database": {
            "type": "string",
            "description": "Path to a SQLite database file (within the workspace).",
        },
        "query": {
            "type": "string",
            "description": "A single SQL statement to execute.",
        },
        "params": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Bind parameters for ? placeholders (avoids injection).",
        },
        "max_rows": {
            "type": "integer",
            "description": f"Max rows to return (1-{_MAX_ROWS_CAP}, default 100).",
        },
        "read_only": {
            "type": "boolean",
            "description": "Reject writes and open the DB read-only. Default true.",
        },
    },
    "required": ["database", "query"],
}


def _looks_like_write(query: str) -> bool:
    stripped = query.lstrip().lstrip("(").lstrip()
    parts = stripped.split(None, 1)
    return bool(parts) and parts[0].lower() in _WRITE_KEYWORDS


def _format_rows(cols: list[str], rows: list[tuple]) -> str:
    header = " | ".join(cols)
    sep = "-+-".join("-" * len(c) for c in cols)
    body = [
        " | ".join("NULL" if v is None else str(v) for v in row)
        for row in rows
    ]
    return "\n".join([header, sep, *body])


def _run_sql_query(args: dict[str, Any], sandbox) -> str:
    database = (args.get("database") or "").strip()
    query = (args.get("query") or "").strip()
    if not database:
        return "ERROR: database is required"
    if not query:
        return "ERROR: query is required"
    read_only = args.get("read_only")
    read_only = True if read_only is None else bool(read_only)
    try:
        max_rows = int(args.get("max_rows") or 100)
    except (TypeError, ValueError):
        max_rows = 100
    max_rows = max(1, min(max_rows, _MAX_ROWS_CAP))
    params = args.get("params") or []
    if not isinstance(params, list):
        return "ERROR: params must be a list"

    try:
        db_path = _safe_path(sandbox, database)
    except ValueError as e:
        return f"ERROR: {e}"
    p = Path(db_path)
    if not p.is_file():
        return f"ERROR: database file not found: {database!r}"

    if read_only and _looks_like_write(query):
        return "ERROR: write statement rejected in read-only mode (set read_only=false to allow)"

    conn = None
    try:
        if read_only:
            # mode=ro: the engine itself refuses any write, regardless of SQL.
            conn = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
        else:
            conn = sqlite3.connect(str(p), timeout=10)
        cur = conn.execute(query, params)
        if cur.description is None:
            conn.commit()
            return f"OK: {cur.rowcount} row(s) affected"
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(max_rows)
        truncated = cur.fetchone() is not None
        out = _format_rows(cols, rows)
        summary = f"\n({len(rows)} row(s)" + (f", truncated at {max_rows}" if truncated else "") + ")"
        return (out + summary)[:_MAX_OUTPUT]
    except (sqlite3.Error, sqlite3.Warning) as e:
        # sqlite3.Warning (not a subclass of Error) is what Python <=3.10
        # raises for a multi-statement execute(); 3.11+ raises ProgrammingError.
        return f"ERROR: sqlite: {e}"
    finally:
        if conn is not None:
            conn.close()


def sql_query(sandbox=None) -> Tool:
    """Factory: builds the sql_query tool."""
    return Tool(
        name="sql_query",
        description=(
            "Run a SQL query against a local SQLite database file. "
            "Read-only by default (writes are rejected and the DB is opened "
            "read-only); pass read_only=false to allow INSERT/UPDATE/etc. "
            "Use `params` for ? placeholders, `max_rows` to cap output. "
            "Returns a formatted table."
        ),
        input_schema=_SQL_QUERY_SCHEMA,
        fn=lambda args: _run_sql_query(args, sandbox),
    )
