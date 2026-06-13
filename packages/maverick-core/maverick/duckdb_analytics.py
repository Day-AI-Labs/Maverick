"""DuckDB analytics over the world model (roadmap: 2027 H2 ecosystem).

The roadmap lists a "DuckDB world-model". As the *live transactional* store
that's the wrong tool — DuckDB is an OLAP engine, and the agent's world model
is a concurrent OLTP write path that SQLite (WAL) / Postgres serve correctly.
What DuckDB is genuinely great at is the **analytics** over that history:
percentiles, time-bucketed spend, ad-hoc ``GROUP BY`` across thousands of
goals — queries that are verbose and slow in hand-rolled Python.

So this is the DuckDB layer that earns its keep: load the world model's goals
and episodes into an in-memory DuckDB (no extension download, fully offline)
and run analytical SQL. Read-only by construction — ``query`` refuses anything
that isn't a ``SELECT``/``WITH`` — so it can be exposed to an agent without
becoming a write path. Behind the ``[duckdb]`` extra.
"""
from __future__ import annotations


class WorldAnalytics:
    """In-memory DuckDB loaded from the world model, for analytical queries."""

    def __init__(self, world, *, limit: int = 100000, conn=None):
        try:
            import duckdb
        except ImportError as e:
            raise ImportError(
                "duckdb not installed. Run: pip install 'maverick-agent[duckdb]'") from e
        self._conn = conn or duckdb.connect(":memory:")
        self._load(world, limit)

    def _load(self, world, limit: int) -> None:
        self._conn.execute(
            "CREATE TABLE goals(id BIGINT, title VARCHAR, status VARCHAR)")
        self._conn.execute(
            "CREATE TABLE episodes(goal_id BIGINT, cost DOUBLE, in_tok BIGINT, "
            "out_tok BIGINT, outcome VARCHAR, ended_at DOUBLE)")
        goals = list(world.list_goals(limit=limit))
        if goals:
            self._conn.executemany(
                "INSERT INTO goals VALUES (?, ?, ?)",
                [(g.id, getattr(g, "title", "") or "", getattr(g, "status", None))
                 for g in goals])
        erows = []
        for g in goals:
            for e in world.list_episodes(goal_id=g.id, limit=limit):
                erows.append((
                    g.id, float(getattr(e, "cost_dollars", 0.0) or 0.0),
                    int(getattr(e, "input_tokens", 0) or 0),
                    int(getattr(e, "output_tokens", 0) or 0),
                    getattr(e, "outcome", None),
                    float(getattr(e, "ended_at", 0.0) or 0.0),
                ))
        if erows:
            self._conn.executemany(
                "INSERT INTO episodes VALUES (?, ?, ?, ?, ?, ?)", erows)

    def query(self, sql: str) -> list[dict]:
        """Run a **read-only** analytical query; returns a list of row dicts."""
        s = (sql or "").strip().lstrip("(").lstrip()
        if not s.lower().startswith(("select", "with")):
            raise ValueError("only SELECT / WITH queries are allowed")
        cur = self._conn.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def cost_percentiles(self) -> dict:
        rows = self.query(
            "WITH per_goal AS (SELECT goal_id, sum(cost) c FROM episodes "
            "GROUP BY goal_id HAVING sum(cost) > 0) "
            "SELECT count(*) AS n, "
            "  coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY c), 0) AS p50, "
            "  coalesce(percentile_cont(0.9) WITHIN GROUP (ORDER BY c), 0) AS p90, "
            "  coalesce(percentile_cont(0.99) WITHIN GROUP (ORDER BY c), 0) AS p99, "
            "  coalesce(max(c), 0) AS max_cost FROM per_goal")
        return rows[0] if rows else {}

    def top_goals(self, n: int = 10) -> list[dict]:
        return self.query(
            "SELECT g.id AS id, g.title AS title, sum(e.cost) AS total_cost, "
            "count(*) AS ep_count "
            "FROM episodes e JOIN goals g ON g.id = e.goal_id "
            "GROUP BY g.id, g.title HAVING sum(e.cost) > 0 "
            f"ORDER BY total_cost DESC LIMIT {max(1, int(n))}")

    def daily_cost(self) -> list[dict]:
        return self.query(
            "SELECT strftime(to_timestamp(ended_at), '%Y-%m-%d') AS bucket, "
            "sum(cost) AS spend FROM episodes WHERE ended_at > 0 "
            "GROUP BY bucket ORDER BY bucket")

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # pragma: no cover
            pass


__all__ = ["WorldAnalytics"]
