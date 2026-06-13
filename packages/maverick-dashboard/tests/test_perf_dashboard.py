"""Public perf dashboard: /api/v1/perf + the page."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from maverick_dashboard.app import app  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    import maverick_dashboard.api as api
    monkeypatch.setattr(api, "_PERF_SLA_CACHE", None)
    return TestClient(app)


def test_perf_api_shape(client, monkeypatch, tmp_path):
    # seed a benchmark history file where continuous_benchmark looks
    import maverick.continuous_benchmark as cb
    store = tmp_path / "bench"
    store.mkdir()
    rows = [{"name": "gaia", "score": 0.5, "commit": "a", "t": 1_700_000_000.0},
            {"name": "gaia", "score": 0.6, "commit": "b", "t": 1_710_000_000.0}]
    (store / "gaia.json").write_text(json.dumps(rows))
    monkeypatch.setattr(cb, "_store_path", lambda: store)

    r = client.get("/api/v1/perf")
    assert r.status_code == 200
    d = r.json()
    assert isinstance(d["sla"], list) and d["sla"], "SLA rows measured live"
    for row in d["sla"]:
        assert {"name", "measured", "threshold", "passed"} <= set(row)
    g = d["benchmarks"]["gaia"]
    assert g["runs"] == 2 and g["latest"] == 0.6 and g["best"] == 0.6
    assert g["regression"]["regressed"] is False
    assert d["retrospective"]["trends"]["gaia"]["trend"]


def test_perf_api_empty_history(client, monkeypatch, tmp_path):
    import maverick.continuous_benchmark as cb
    monkeypatch.setattr(cb, "_store_path", lambda: tmp_path / "nope")
    d = client.get("/api/v1/perf").json()
    assert d["benchmarks"] == {} and d["retrospective"] is None


def test_perf_api_caches_live_sla(client, monkeypatch, tmp_path):
    import maverick.continuous_benchmark as cb
    import maverick.perf_sla as perf_sla
    from maverick.perf_sla import SLAResult

    calls = 0

    def fake_run_all():
        nonlocal calls
        calls += 1
        return [SLAResult("fake", 1.0, 2.0, "ms")]

    monkeypatch.setattr(cb, "_store_path", lambda: tmp_path / "nope")
    monkeypatch.setattr(perf_sla, "run_all", fake_run_all)

    assert client.get("/api/v1/perf").status_code == 200
    assert client.get("/api/v1/perf").status_code == 200
    assert calls == 1


def test_perf_page_renders(client):
    r = client.get("/perf")
    assert r.status_code == 200
    assert "/api/v1/perf" in r.text


def test_glance_endpoint_shape(client):
    r = client.get("/api/v1/glance")
    assert r.status_code == 200
    d = r.json()
    assert {"active", "done_today", "failed_today", "spend_today",
            "last_result", "as_of"} == set(d)
