"""Settings: per-goal spend cap, saved to the runtime overlay."""
from __future__ import annotations

from fastapi.testclient import TestClient

_ORIGIN = {"origin": "http://testserver"}


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _prep(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("MAVERICK_BUDGET_DOLLARS", raising=False)
    import maverick.runtime_overrides as ro
    monkeypatch.setattr(ro, "OVERRIDES_PATH", tmp_path / "runtime-overrides.toml")
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()


def test_settings_shows_spend_cap(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    r = _client().get("/settings")
    assert r.status_code == 200
    assert "Spend cap" in r.text
    assert 'action="/settings/budget"' in r.text


def test_set_and_clear_budget(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    c = _client()
    r = c.post("/settings/budget", data={"max_dollars": "1.5"},
               headers=_ORIGIN, follow_redirects=False)
    assert r.status_code == 303

    from maverick.runtime_overrides import budget_override
    assert budget_override() == 1.5
    # the cap flows through budget resolution
    from maverick.budget import budget_from_config
    assert budget_from_config().max_dollars == 1.5

    r = c.post("/settings/budget", data={"max_dollars": ""},
               headers=_ORIGIN, follow_redirects=False)
    assert r.status_code == 303
    assert budget_override() is None


def test_budget_rejects_nonpositive(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    for bad in ("0", "-2", "abc"):
        r = _client().post("/settings/budget", data={"max_dollars": bad},
                           headers=_ORIGIN, follow_redirects=False)
        assert r.status_code == 400, bad


def test_budget_blocks_cross_origin(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    r = _client().post("/settings/budget", data={"max_dollars": "5"},
                       headers={"origin": "http://evil.example"},
                       follow_redirects=False)
    assert r.status_code == 403
