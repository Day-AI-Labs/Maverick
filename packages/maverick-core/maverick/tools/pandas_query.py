"""Data analysis tool: pandas-backed CSV / Parquet / JSON queries.

Runs simple read + describe + filter + groupby operations on a
file the agent points it at. Result is rendered as a compact text
table so it fits in tool-result token budgets.

The tool is intentionally LIMITED: it doesn't accept arbitrary
``df.eval()`` strings (that's a code-execution vector). Instead,
each op is a typed verb the tool function understands.

Optional [pandas] extra installs pandas + pyarrow (for parquet).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_PANDAS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["head", "describe", "value_counts", "filter", "groupby"],
            "description": "Operation.",
        },
        "source": {
            "type": "string",
            "description": "Path to the file (csv / parquet / json / jsonl).",
        },
        "column": {"type": "string", "description": "Target column (value_counts, groupby)."},
        "agg": {
            "type": "string",
            "enum": ["count", "sum", "mean", "median", "min", "max", "std"],
            "description": "Aggregation function (groupby).",
        },
        "agg_column": {"type": "string", "description": "Column to aggregate (groupby)."},
        "where": {
            "type": "string",
            "description": "Filter expression: 'column op value' (e.g. 'age > 25').",
        },
        "n": {"type": "integer", "description": "Row limit (default 20)."},
    },
    "required": ["op", "source"],
}


def _load(path: Path):
    try:
        import pandas as pd
    except ImportError as e:
        raise ImportError(
            "pandas not installed. Run: pip install 'maverick-agent[pandas]'"
        ) from e
    ext = path.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path)
    if ext == ".parquet":
        return pd.read_parquet(path)
    if ext == ".json":
        return pd.read_json(path)
    if ext == ".jsonl":
        return pd.read_json(path, lines=True)
    raise ValueError(f"unsupported file extension: {ext}")


def _apply_where(df, where: str):
    """Parse a single 'col op value' clause. Safer than df.query()."""
    import re
    m = re.match(
        r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=|<=|>=|<|>)\s*(.+?)\s*$",
        where,
    )
    if not m:
        raise ValueError(
            f"where clause must be `column op value`; got {where!r}"
        )
    col, op_, raw = m.group(1), m.group(2), m.group(3).strip()
    # Coerce the value: int, float, or string literal.
    if raw.startswith(("'", '"')) and raw.endswith(("'", '"')):
        val = raw[1:-1]
    else:
        try:
            val = int(raw)
        except ValueError:
            try:
                val = float(raw)
            except ValueError:
                val = raw
    series = df[col]
    if op_ == "==":
        return df[series == val]
    if op_ == "!=":
        return df[series != val]
    if op_ == "<":
        return df[series < val]
    if op_ == "<=":
        return df[series <= val]
    if op_ == ">":
        return df[series > val]
    if op_ == ">=":
        return df[series >= val]
    raise ValueError(f"unsupported op: {op_}")


def _fmt(df, *, max_rows: int = 20) -> str:
    """Compact text table; truncate to keep token cost bounded."""
    try:
        return df.head(max_rows).to_string(index=True, max_cols=20)
    except Exception:
        # Fallback for non-DataFrame results (Series, scalars).
        return str(df)


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    src = (args.get("source") or "").strip()
    if not op:
        return "ERROR: op is required"
    if not src:
        return "ERROR: source is required"
    path = Path(os.path.expanduser(src))
    if not path.exists() or not path.is_file():
        return f"ERROR: file not found: {src!r}"

    try:
        df = _load(path)
    except ImportError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: cannot load {src!r}: {type(e).__name__}: {e}"

    n = max(1, min(int(args.get("n") or 20), 200))
    where = args.get("where")
    if where:
        try:
            df = _apply_where(df, where)
        except Exception as e:
            return f"ERROR: bad where clause: {e}"

    try:
        if op == "head":
            return _fmt(df, max_rows=n)
        if op == "describe":
            return df.describe(include="all").to_string()
        if op == "value_counts":
            col = (args.get("column") or "").strip()
            if not col:
                return "ERROR: value_counts requires column"
            return df[col].value_counts().head(n).to_string()
        if op == "filter":
            return _fmt(df, max_rows=n)
        if op == "groupby":
            col = (args.get("column") or "").strip()
            agg_col = (args.get("agg_column") or "").strip()
            agg_fn = (args.get("agg") or "count").strip()
            if not col:
                return "ERROR: groupby requires column"
            grouped = df.groupby(col)
            if not agg_col or agg_fn == "count":
                result = grouped.size().sort_values(ascending=False)
            else:
                result = grouped[agg_col].agg(agg_fn).sort_values(ascending=False)
            return result.head(n).to_string()
    except Exception as e:
        return f"ERROR: {op} failed: {type(e).__name__}: {e}"
    return f"ERROR: unknown op {op!r}"


def pandas_query() -> Tool:
    return Tool(
        name="pandas_query",
        description=(
            "Tabular data analysis over csv / parquet / json / jsonl "
            "files. ops: head (top n rows), describe (summary stats), "
            "value_counts (frequency table for one column), filter "
            "(with where clause like 'age > 25'), groupby (with agg: "
            "count / sum / mean / median / min / max / std). Loaded "
            "via pandas; install with: pip install "
            "'maverick-agent[pandas]'."
        ),
        input_schema=_PANDAS_SCHEMA,
        fn=_run,
    )
