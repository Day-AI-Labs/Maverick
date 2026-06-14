"""AI workflow builder: draft (chat + upload) -> edit -> save as a template.

Hermetic like the other dashboard tests: HOME/MAVERICK_HOME isolated to tmp,
the WorldModel + the template store (USER_TEMPLATES is import-time bound, so
monkeypatch it) point under tmp, and no provider key is needed because the LLM
call is either injected or the endpoint's `draft_workflow` is monkeypatched.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _client():
    # Mutating /api/v1 requests in no-token mode must pass the same-origin CSRF check.
    from maverick_dashboard.app import app
    return TestClient(app, headers={"Origin": "http://testserver"})


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    import maverick.templates as tpl
    monkeypatch.setattr(tpl, "USER_TEMPLATES", tmp_path / ".maverick" / "templates")


# --- pure parsing / prompt building (no LLM) --------------------------------

def test_parse_workflow_normalizes():
    from maverick_dashboard.workflow_ai import parse_workflow
    d = parse_workflow(
        '{"name": "Weekly Report!", "title": "Weekly {{topic}} report", '
        '"params": ["topic", "bad-name", "topic"], "steps": ["a", "b", "  "], '
        '"budget_dollars": 99}'
    )
    assert d["name"] == "weekly-report"            # slugified
    assert d["title"] == "Weekly {{topic}} report"
    assert d["params"] == ["topic"]                # non-identifier + dup dropped
    assert d["steps"] == ["a", "b"]                # blank dropped
    assert d["budget_dollars"] == 20.0             # clamped to the max
    assert "1. a" in d["body"] and "2. b" in d["body"]


def test_parse_workflow_strips_code_fence():
    from maverick_dashboard.workflow_ai import parse_workflow
    d = parse_workflow('```json\n{"name":"x","title":"X","steps":["do it"]}\n```')
    assert d["name"] == "x" and d["steps"] == ["do it"]


def test_parse_workflow_rejects_unusable():
    from maverick_dashboard.workflow_ai import parse_workflow
    with pytest.raises(ValueError):
        parse_workflow("not json at all")
    with pytest.raises(ValueError):
        parse_workflow('{"title": "x", "steps": []}')   # no steps -> unusable


def test_build_prompt_includes_brief_and_doc():
    from maverick_dashboard.workflow_ai import build_prompt
    p = build_prompt("my brief", "DOC BODY TEXT")
    assert "my brief" in p and "DOC BODY TEXT" in p


def test_draft_workflow_uses_injected_complete_under_cap():
    from maverick_dashboard import workflow_ai

    seen = {}

    class _Resp:
        text = '{"name":"demo","title":"Demo","steps":["step one"],"budget_dollars":2}'

    def fake_complete(*, system, messages, budget, max_tokens, model):
        seen["system"] = system
        seen["budget"] = budget
        return _Resp()

    d = workflow_ai.draft_workflow("do a thing", complete=fake_complete)
    assert d["name"] == "demo" and d["steps"] == ["step one"]
    assert d["budget_dollars"] == 2.0
    # Drafting is hard-capped (kernel rule: budget caps are not optional).
    assert seen["budget"].max_dollars == workflow_ai.DRAFT_MAX_DOLLARS
    assert "STRICT JSON" in seen["system"]


# --- core writer ------------------------------------------------------------

def test_save_user_template_round_trips(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick.templates import load_template, save_user_template
    tpl = save_user_template(
        "trip-plan", title="Plan {{dest}}", body="## Steps\n1. go",
        params=["dest"], budget_dollars=3.0,
    )
    assert tpl.name == "trip-plan"
    loaded = load_template("trip-plan")
    assert loaded.title == "Plan {{dest}}"
    assert loaded.params == ["dest"]
    assert loaded.budget_dollars == 3.0
    title, _body = loaded.render(dest="Lisbon")
    assert title == "Plan Lisbon"


def test_save_user_template_validates(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick.templates import save_user_template
    with pytest.raises(ValueError):
        save_user_template("../escape", title="x", body="y")
    with pytest.raises(ValueError):
        save_user_template("ok", title="x", body="   ")   # empty body


# --- endpoints --------------------------------------------------------------

def _stub_draft(monkeypatch, draft):
    from maverick_dashboard import workflow_ai
    monkeypatch.setattr(workflow_ai, "draft_workflow", lambda *a, **k: draft)


def _provider(monkeypatch, present):
    import maverick_dashboard.api as api
    monkeypatch.setattr(api, "_any_provider_key_set", lambda: present)


def test_draft_endpoint_returns_draft(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _provider(monkeypatch, True)
    _stub_draft(monkeypatch, {"name": "x", "title": "X", "params": [],
                              "steps": ["s"], "body": "## Steps\n1. s", "budget_dollars": 5.0})
    r = _client().post("/api/v1/workflows/draft", json={"description": "build me a thing"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "x"


def test_draft_endpoint_needs_provider_key(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _provider(monkeypatch, False)
    r = _client().post("/api/v1/workflows/draft", json={"description": "x"})
    assert r.status_code == 400
    assert "provider" in r.json()["detail"].lower()


def test_draft_endpoint_requires_a_brief(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _provider(monkeypatch, True)
    r = _client().post("/api/v1/workflows/draft", json={"description": "   "})
    assert r.status_code == 400


def test_draft_from_file_feeds_text(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _provider(monkeypatch, True)
    captured = {}
    from maverick_dashboard import workflow_ai

    def fake(brief="", source_text="", **k):
        captured["src"] = source_text
        return {"name": "doc-wf", "title": "Doc", "params": [],
                "steps": ["s"], "body": "b", "budget_dollars": 5.0}

    monkeypatch.setattr(workflow_ai, "draft_workflow", fake)
    r = _client().post(
        "/api/v1/workflows/draft-from-file",
        files={"file": ("spec.md", b"Build a weekly report workflow", "text/markdown")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "doc-wf"
    assert "weekly report" in captured["src"].lower()


def test_draft_from_file_rejects_binary(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _provider(monkeypatch, True)
    r = _client().post(
        "/api/v1/workflows/draft-from-file",
        files={"file": ("x.bin", b"\xff\xfe\x00\x01\x02", "application/octet-stream")},
    )
    assert r.status_code == 400


def test_save_endpoint_persists_a_runnable_template(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = _client().post("/api/v1/workflows", json={
        "name": "my-wf", "title": "My WF", "body": "## Steps\n1. do it",
        "params": ["x"], "budget_dollars": 4.0,
    })
    assert r.status_code == 201, r.text
    assert r.json()["saved"] is True
    from maverick.templates import load_template
    assert load_template("my-wf").title == "My WF"


def test_save_endpoint_rejects_bad_name(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = _client().post("/api/v1/workflows", json={
        "name": "../etc/passwd", "title": "x", "body": "## Steps\n1. y",
    })
    assert r.status_code == 400


def test_workflow_builder_page_renders(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = _client().get("/workflow-builder")
    assert r.status_code == 200
    assert '<h1 class="page-title">Workflow builder</h1>' in r.text
    assert 'id="wf-draft-btn"' in r.text
    assert "/api/v1/workflows/draft" in r.text
    # Reachable from the primary nav (Operate group).
    assert '<span class="nav-label">Workflows</span>' in r.text
