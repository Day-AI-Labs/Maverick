"""Inbound webhook triggers: manage via /api/v1/triggers, fire via /webhook/run.

Management is dashboard-authed + operate-gated + feature-knobbed; firing is
HMAC-signed exactly like /webhook/start and strictly narrower (it runs only an
operator-registered template, never arbitrary text). Hermetic: HOME is isolated
to tmp so the trigger registry, templates, and world model all live under tmp;
the background runner is stubbed so no real goal runs.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

SECRET = "test-webhook-secret"  # pragma: allowlist secret


def _client():
    # Mutating /api/v1 requests in no-token mode need the same-origin CSRF header;
    # the HMAC-exempt /webhook/run ignores it.
    from maverick_dashboard.app import app
    return TestClient(app, headers={"Origin": "http://testserver"})


def _sign_headers(body: bytes) -> dict:
    ts = str(int(time.time()))
    material = f"{ts}.".encode() + body
    sig = "sha256=" + hmac.new(SECRET.encode(), material, hashlib.sha256).hexdigest()
    return {"X-Maverick-Signature": sig, "X-Maverick-Timestamp": ts}


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_CONFIG", raising=False)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("MAVERICK_WEBHOOK_SECRET", raising=False)
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    import maverick.templates as tpl
    tdir = tmp_path / ".maverick" / "templates"
    monkeypatch.setattr(tpl, "USER_TEMPLATES", tdir)
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "weekly-report.md").write_text(
        "---\ntitle: Weekly {{topic}} report\nparams:\n  - topic\n---\n"
        "Research {{topic}} and email the team.\n", encoding="utf-8")


@pytest.fixture
def _no_real_run(monkeypatch):
    import maverick.runner as runner_mod
    called = []

    def fake_run(goal_id, max_dollars=None, max_wall_seconds=None, max_depth=3):
        called.append(goal_id)

    monkeypatch.setattr(runner_mod, "run_goal_in_thread", fake_run)
    return called


def _configured(monkeypatch):
    monkeypatch.setenv("MAVERICK_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")


def _register(c, **kw):
    payload = {"template": "weekly-report", "params": {"topic": "rivals"}}
    payload.update(kw)
    r = c.post("/api/v1/triggers", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["name"]


# ---- management REST ---------------------------------------------------------

def test_create_list_delete_trigger(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    c = _client()
    r = c.post("/api/v1/triggers",
               json={"template": "weekly-report", "params": {"topic": "rivals"}})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "weekly-report" and body["template"] == "weekly-report"
    assert body["params"] == {"topic": "rivals"} and body["webhook_url"] == "/webhook/run"
    assert body["secret_configured"] is False          # no [webhooks] secret here
    listed = c.get("/api/v1/triggers").json()
    assert any(t["name"] == "weekly-report" for t in listed["triggers"])
    assert listed["webhook_url"] == "/webhook/run"
    assert c.delete("/api/v1/triggers/weekly-report").status_code == 200
    assert c.delete("/api/v1/triggers/weekly-report").status_code == 404
    assert c.get("/api/v1/triggers").json()["triggers"] == []


def test_create_trigger_validates_template(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    c = _client()
    # a missing required param fails at registration (render raises ValueError)
    assert c.post("/api/v1/triggers",
                  json={"template": "weekly-report"}).status_code == 400
    # an unknown template is a 404
    assert c.post("/api/v1/triggers",
                  json={"template": "nope", "params": {}}).status_code == 404


def test_triggers_feature_off_403(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick import config
    real = config.get_features
    monkeypatch.setattr(config, "get_features", lambda: {**real(), "triggers": False})
    c = _client()
    assert c.post("/api/v1/triggers", json={
        "template": "weekly-report", "params": {"topic": "x"}}).status_code == 403
    assert c.get("/api/v1/triggers").status_code == 200    # read-only stays open


# ---- inbound /webhook/run (HMAC-signed) -------------------------------------

def test_webhook_run_fires_registered_template(monkeypatch, tmp_path, _no_real_run):
    _isolate(monkeypatch, tmp_path)
    _configured(monkeypatch)
    c = _client()
    name = _register(c)
    body = json.dumps({"trigger": name}).encode()
    r = c.post("/webhook/run", content=body, headers=_sign_headers(body))
    assert r.status_code == 201, r.text
    goal_id = r.json()["goal_id"]
    assert _no_real_run == [goal_id]
    from maverick.world_model import DEFAULT_DB, WorldModel
    g = WorldModel(DEFAULT_DB).get_goal(goal_id)
    assert g is not None and g.title == "Weekly rivals report"   # rendered defaults


def test_webhook_run_records_trigger_provenance(monkeypatch, tmp_path, _no_real_run):
    # v2: firing a trigger stamps goal_origins, so /automation-runs (same _world)
    # surfaces the spawned goal for the Automations run-history view.
    _isolate(monkeypatch, tmp_path)
    _configured(monkeypatch)
    c = _client()
    name = _register(c)
    body = json.dumps({"trigger": name}).encode()
    gid = c.post("/webhook/run", content=body, headers=_sign_headers(body)).json()["goal_id"]
    data = c.get("/api/v1/automation-runs", params={"kind": "trigger", "ref": name}).json()
    assert any(r["goal_id"] == gid for r in data["runs"])
    assert sum(data["summary"].values()) >= 1


def test_webhook_run_inbound_overrides_declared_param(monkeypatch, tmp_path, _no_real_run):
    _isolate(monkeypatch, tmp_path)
    _configured(monkeypatch)
    c = _client()
    name = _register(c)            # default topic=rivals
    # inbound data overrides the DECLARED "topic"; an undeclared key is ignored
    body = json.dumps({"trigger": name, "data": {"topic": "acme", "evil": "x"}}).encode()
    r = c.post("/webhook/run", content=body, headers=_sign_headers(body))
    assert r.status_code == 201
    from maverick.world_model import DEFAULT_DB, WorldModel
    g = WorldModel(DEFAULT_DB).get_goal(r.json()["goal_id"])
    assert g.title == "Weekly acme report"


def test_webhook_run_unknown_trigger_404(monkeypatch, tmp_path, _no_real_run):
    _isolate(monkeypatch, tmp_path)
    _configured(monkeypatch)
    body = json.dumps({"trigger": "ghost"}).encode()
    r = _client().post("/webhook/run", content=body, headers=_sign_headers(body))
    assert r.status_code == 404
    assert _no_real_run == []


def test_webhook_run_bad_signature_403(monkeypatch, tmp_path, _no_real_run):
    _isolate(monkeypatch, tmp_path)
    _configured(monkeypatch)
    c = _client()
    name = _register(c)
    body = json.dumps({"trigger": name}).encode()
    r = c.post("/webhook/run", content=body, headers={
        "X-Maverick-Signature": "sha256=bad",
        "X-Maverick-Timestamp": str(int(time.time())),
    })
    assert r.status_code == 403
    assert _no_real_run == []


def test_webhook_run_no_secret_fails_closed(monkeypatch, tmp_path, _no_real_run):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")    # but NO webhook secret
    import maverick.webhooks as wh
    monkeypatch.setattr(wh, "_load_config_outbound", lambda: ([], None))
    c = _client()
    name = _register(c)                                       # managing needs no secret
    body = json.dumps({"trigger": name}).encode()
    r = c.post("/webhook/run", content=body, headers=_sign_headers(body))
    assert r.status_code == 401
    assert _no_real_run == []


def test_webhook_run_feature_off_404(monkeypatch, tmp_path, _no_real_run):
    _isolate(monkeypatch, tmp_path)
    _configured(monkeypatch)
    c = _client()
    name = _register(c)
    from maverick import config
    real = config.get_features
    monkeypatch.setattr(config, "get_features", lambda: {**real(), "triggers": False})
    body = json.dumps({"trigger": name}).encode()
    r = c.post("/webhook/run", content=body, headers=_sign_headers(body))
    assert r.status_code == 404
    assert _no_real_run == []


# ---- store slug / round-trip -------------------------------------------------

def test_store_slugifies_and_round_trips(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick_dashboard import triggers_store as ts
    rec = ts.set_trigger("My Weekly Report!", "weekly-report", {"topic": "rivals"})
    assert rec["name"] == "my-weekly-report"
    got = ts.get_trigger("my-weekly-report")
    assert got is not None and got["params"] == {"topic": "rivals"}
    with pytest.raises(ValueError):
        ts.set_trigger("!!!", "weekly-report", {})          # un-sluggable name


def test_concurrent_set_trigger_does_not_lose_triggers(monkeypatch, tmp_path):
    """set_trigger does a load-modify-save; without the lock concurrent creates
    clobber each other. All N distinct triggers must survive."""
    import threading

    from maverick_dashboard import triggers_store
    n = 16

    def add(i: int):
        triggers_store.set_trigger(f"trig-{i:03d}", "some-template")

    threads = [threading.Thread(target=add, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(triggers_store.list_triggers()) == n
    store_dir = triggers_store._path().parent
    assert list(store_dir.glob("*.tmp")) == []
