"""DuckDB analytics over the world model: load, canned queries, read-only guard."""
from __future__ import annotations

import pytest
from click.testing import CliRunner
from maverick.cli import main
from maverick.world_model import WorldModel

pytest.importorskip("duckdb")
from maverick.duckdb_analytics import WorldAnalytics  # noqa: E402


def _seed(path, goals):
    """goals: list of (title, status, [(cost, outcome, ended_at), ...])."""
    wm = WorldModel(path)
    for title, status, eps in goals:
        gid = wm.create_goal(title, "")
        if status:
            wm.set_goal_status(gid, status)
        for cost, outcome, _ended in eps:
            ep = wm.start_episode(gid)
            wm.end_episode(ep, summary="s", outcome=outcome, cost_dollars=cost)
    wm.close()
    return WorldModel(path)


def test_cost_percentiles(tmp_path):
    w = _seed(tmp_path / "w.db", [
        (f"g{i}", "done", [(float(i) * 0.5, "success", 1.0)]) for i in range(1, 11)
    ])
    wa = WorldAnalytics(w)
    pct = wa.cost_percentiles()
    assert pct["n"] == 10
    assert pct["max_cost"] == pytest.approx(5.0)
    assert 0 < pct["p50"] <= pct["p90"] <= pct["p99"] <= pct["max_cost"]
    wa.close()


def test_top_goals(tmp_path):
    w = _seed(tmp_path / "w.db", [
        ("cheap", "done", [(0.1, "success", 1.0)]),
        ("whale", "done", [(5.0, "success", 1.0), (1.0, "success", 1.0)]),
        ("free", "done", [(0.0, "success", 1.0)]),
    ])
    wa = WorldAnalytics(w)
    rows = wa.top_goals(5)
    assert rows[0]["title"] == "whale" and rows[0]["total_cost"] == pytest.approx(6.0)
    assert rows[0]["ep_count"] == 2
    assert all(r["title"] != "free" for r in rows)  # zero-cost excluded
    wa.close()


def test_daily_cost(tmp_path):
    w = _seed(tmp_path / "w.db", [("g", "done", [(1.0, "success", 1.0)])])
    wa = WorldAnalytics(w)
    days = wa.daily_cost()
    # end_episode stamps ended_at = now, so there's one day bucket at today.
    assert len(days) == 1 and days[0]["spend"] == pytest.approx(1.0)
    import re
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", days[0]["bucket"])
    wa.close()


def test_adhoc_query(tmp_path):
    w = _seed(tmp_path / "w.db", [("a", "done", [(2.0, "success", 1.0)])])
    wa = WorldAnalytics(w)
    rows = wa.query("SELECT count(*) AS n FROM episodes")
    assert rows == [{"n": 1}]
    wa.close()


def test_query_rejects_writes(tmp_path):
    w = _seed(tmp_path / "w.db", [("a", "done", [(1.0, "success", 1.0)])])
    wa = WorldAnalytics(w)
    for bad in ("DELETE FROM episodes", "DROP TABLE goals",
                "UPDATE goals SET title='x'", "INSERT INTO goals VALUES (1,'x','y')"):
        with pytest.raises(ValueError, match="only SELECT"):
            wa.query(bad)
    wa.close()


def test_empty_world(tmp_path):
    w = WorldModel(tmp_path / "w.db")
    wa = WorldAnalytics(w)
    assert wa.cost_percentiles().get("n") == 0
    assert wa.top_goals() == []
    wa.close()


def test_cli_analytics(tmp_path):
    db = tmp_path / "world.db"
    _seed(db, [("g", "done", [(1.5, "success", 1.0)])]).close()
    res = CliRunner().invoke(main, ["--db", str(db), "analytics"])
    assert res.exit_code == 0
    assert "cost percentiles" in res.output.lower()
    assert "Costliest goals" in res.output


def test_cli_analytics_sql(tmp_path):
    db = tmp_path / "world.db"
    _seed(db, [("g", "done", [(1.0, "success", 1.0)])]).close()
    res = CliRunner().invoke(
        main, ["--db", str(db), "analytics", "--sql", "SELECT count(*) n FROM goals"])
    assert res.exit_code == 0
    import json
    assert json.loads(res.output) == [{"n": 1}]
