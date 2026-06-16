"""The goal page renders a structured result as the deliverable its pack
declares -- a forecast as a real grid with a titled, gated card -- and leaves a
generic goal as today's plain prose."""
from __future__ import annotations

from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app)

_FORECAST_RESULT = """\
Rolling 13-week cash forecast, every figure tied to its system of record.

| Week | Inflows | Outflows | Net |
| --- | ---: | ---: | ---: |
| W1 | 1,200 | 900 | 300 |
| W2 | 1,100 | 1,000 | 100 |
"""


def _world(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    return world_model.WorldModel(tmp_path / "world.db")


def test_forecast_goal_renders_as_a_deliverable_grid(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    gid = w.create_goal("Refresh the cash forecast", "", domain="finance_cash13w")
    w.set_goal_status(gid, "done", result=_FORECAST_RESULT)

    t = client.get(f"/chat/goal/{gid}").text
    # Titled, gated deliverable card keyed off the pack's output contract.
    assert "13-week cash forecast" in t
    assert "review gate" in t
    assert "fpa_analyst" in t
    # The result is a real table, not a <pre> dump.
    assert '<table class="deliverable__table">' in t
    assert "<th scope=\"col\">Week</th>" in t
    assert "<td>1,200</td>" in t


def test_generic_goal_keeps_plain_prose(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    gid = w.create_goal("Summarize the meeting", "")  # no domain -> no contract
    w.set_goal_status(gid, "done", result="A short prose summary.")

    t = client.get(f"/chat/goal/{gid}").text
    assert '<pre id="result"' in t
    assert "A short prose summary." in t
    # No deliverable card is rendered (the .deliverable__table *style* is always
    # present in the page's <style> block; assert on the rendered markup).
    assert '<table class="deliverable__table">' not in t
    assert 'class="deliverable__head"' not in t
    assert "review gate" not in t
