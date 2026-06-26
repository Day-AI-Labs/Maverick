"""Dashboard endpoints for importing external automations into Lightwork.

Hermetic like the other dashboard tests: HOME/MAVERICK_HOME isolated to tmp,
USER_TEMPLATES (import-time bound) monkeypatched, the world DB under tmp. The
import feature is gated, so the gate env is set on.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setenv("MAVERICK_AUTOMATION_IMPORT", "1")
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    import maverick.templates as tpl
    monkeypatch.setattr(tpl, "USER_TEMPLATES", tmp_path / ".maverick" / "templates")


N8N_WF = {
    "id": "1", "name": "Lead to Slack", "active": True,
    "nodes": [
        {"name": "Hook", "type": "n8n-nodes-base.webhook", "parameters": {}},
        {"name": "Notify", "type": "n8n-nodes-base.slack", "parameters": {"operation": "post"}},
    ],
    "connections": {"Hook": {"main": [[{"node": "Notify"}]]}},
}


N8N_CRON_WF = {
    "id": "2", "name": "Daily digest", "active": True,
    "nodes": [
        {"name": "Every morning", "type": "n8n-nodes-base.cron",
         "parameters": {"cronExpression": "0 9 * * *"}},
        {"name": "Send email", "type": "n8n-nodes-base.emailSend",
         "parameters": {"operation": "send"}},
    ],
    "connections": {
        "Every morning": {"main": [[{"node": "Send email", "type": "main", "index": 0}]]},
    },
}


class _FakeQueue:
    last = None

    def __init__(self):
        self.enqueued = []
        type(self).last = self

    def enqueue(self, kind, payload, run_at=None):
        self.enqueued.append((kind, payload, run_at))
        return len(self.enqueued)


def test_sources_lists_modes():
    r = _client().get("/api/v1/import/sources")
    assert r.status_code == 200
    sources = {s["source"]: s["mode"] for s in r.json()["sources"]}
    assert sources["n8n"] == "definition-import"
    assert sources["zapier"] == "connect-and-trigger"


def test_run_creates_template_from_definitions():
    r = _client().post("/api/v1/import/run", json={
        "source": "n8n", "definitions": [N8N_WF],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False
    assert len(body["imported"]) == 1
    item = body["imported"][0]
    assert item["template"].startswith("n8n-lead-to-slack-")
    assert item["created"] is True
    assert item["trigger"] == "webhook"
    # The template now exists.
    from maverick.templates import load_template
    assert load_template(item["template"]) is not None


def test_dry_run_writes_nothing():
    r = _client().post("/api/v1/import/run", json={
        "source": "n8n", "definitions": [N8N_WF], "dry_run": True,
    })
    assert r.status_code == 200
    item = r.json()["imported"][0]
    assert item["created"] is False
    from maverick.templates import load_template
    with pytest.raises(FileNotFoundError):
        load_template(item["template"])


def test_create_webhook_trigger_wires_it():
    r = _client().post("/api/v1/import/run", json={
        "source": "n8n", "definitions": [N8N_WF], "create_webhook_triggers": True,
    })
    assert r.status_code == 200
    item = r.json()["imported"][0]
    assert item["webhook_trigger"] == item["template"]
    from maverick_dashboard import triggers_store
    assert triggers_store.get_trigger(item["template"]) is not None


def test_webhook_trigger_respects_features_gate(monkeypatch):
    # When [features] triggers is off, the import must NOT create webhook
    # triggers (it would bypass the operator's deliberate decision).
    import maverick.config as cfg
    real = cfg.get_features
    monkeypatch.setattr(cfg, "get_features", lambda: {**real(), "triggers": False})
    r = _client().post("/api/v1/import/run", json={
        "source": "n8n", "definitions": [N8N_WF], "create_webhook_triggers": True,
    })
    assert r.status_code == 200
    item = r.json()["imported"][0]
    assert item["webhook_trigger"] is None
    assert any("triggers is off" in n for n in item["notes"])


def test_activate_schedules_preserves_request_identity(monkeypatch):
    import maverick.job_queue as job_queue
    import maverick_dashboard.api as api

    _FakeQueue.last = None
    monkeypatch.setattr(job_queue, "JobQueue", _FakeQueue)
    monkeypatch.setattr(api, "caller_principal", lambda request: "user:alice")
    monkeypatch.setattr(api, "execution_user_id_from_request", lambda request: "alice")

    r = _client().post("/api/v1/import/run", json={
        "source": "n8n",
        "definitions": [N8N_CRON_WF],
        "activate_schedules": True,
    })
    assert r.status_code == 200, r.text
    assert _FakeQueue.last is not None
    payload = _FakeQueue.last.enqueued[0][1]
    assert payload["owner"] == "user:alice"
    assert payload["channel"] == "api"
    assert payload["user_id"] == "alice"


def test_gate_blocks_when_disabled(monkeypatch):
    monkeypatch.setenv("MAVERICK_AUTOMATION_IMPORT", "0")
    r = _client().post("/api/v1/import/run", json={"source": "n8n", "definitions": [N8N_WF]})
    assert r.status_code == 403


def test_unknown_source_400():
    r = _client().post("/api/v1/import/run", json={"source": "nope", "definitions": [{}]})
    assert r.status_code == 400


def test_connect_source_live_fetch_400():
    # zapier has no definitions to fetch; omitting definitions -> fetch() raises 400.
    r = _client().post("/api/v1/import/run", json={"source": "zapier"})
    assert r.status_code == 400
    assert "webhook" in r.json()["detail"].lower()


def test_automations_page_shows_import_section_when_enabled():
    r = _client().get("/automations")
    assert r.status_code == 200
    assert "Import from another platform" in r.text
    assert 'id="auto-import-form"' in r.text


def test_automations_page_hides_import_when_disabled(monkeypatch):
    monkeypatch.setenv("MAVERICK_AUTOMATION_IMPORT", "0")
    r = _client().get("/automations")
    assert r.status_code == 200
    assert "Import from another platform" not in r.text


def test_run_rejects_too_many_definitions():
    definitions = [dict(N8N_WF, id=str(i), name=f"WF {i}") for i in range(26)]
    r = _client().post("/api/v1/import/run", json={"source": "n8n", "definitions": definitions})
    assert r.status_code == 422


def test_run_rejects_oversized_definition():
    wf = dict(N8N_WF)
    wf["nodes"] = [
        {"name": "Hook", "type": "n8n-nodes-base.webhook", "parameters": {}},
        {
            "name": "Notify",
            "type": "n8n-nodes-base.slack",
            "parameters": {"operation": "post", "body": "x" * 65_000},
        },
    ]
    r = _client().post("/api/v1/import/run", json={"source": "n8n", "definitions": [wf]})
    assert r.status_code == 413
