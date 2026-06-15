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
    # The playbook form saves a domain pack via /agents/<name>/override; point the
    # user domains dir at tmp so a test never writes to the real ~/.maverick/domains.
    monkeypatch.setenv("MAVERICK_DOMAINS_DIR", str(tmp_path / "domains"))
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


# --- playbook parsing / drafting (no LLM) -----------------------------------

def test_parse_playbook_normalizes():
    from maverick_dashboard.workflow_ai import parse_playbook
    d = parse_playbook(
        '{"name": "AP Invoice Bot!", "description": "  Pays   invoices ", '
        '"persona": "You are careful.", "max_risk": "EXTREME", '
        '"steps": [{"name": "Read", "instruction": "ocr", "tools": ["ocr_read"], "gate": "maybe"}, '
        '{"name": "Pay", "instruction": "pay", "tools": ["send_payment"], "gate": "APPROVAL"}, '
        '{"name": "  ", "instruction": "dropped"}]}'
    )
    assert d["form"] == "playbook"
    assert d["name"] == "ap-invoice-bot"                 # slugified
    assert d["description"] == "Pays invoices"           # whitespace collapsed
    assert d["max_risk"] == "medium"                     # unknown risk -> default
    assert [s["gate"] for s in d["workflow"]] == [None, "approval"]  # bad gate dropped; cased
    assert len(d["workflow"]) == 2                       # nameless step dropped
    # No top-level allow_tools -> derive the allowlist from the steps' own tools.
    assert d["allow_tools"] == ["ocr_read", "send_payment"]


def test_parse_playbook_keeps_explicit_allowlist_and_strips_fence():
    from maverick_dashboard.workflow_ai import parse_playbook
    d = parse_playbook(
        '```json\n{"name":"x","allow_tools":["a","b"],"deny_tools":["shell"],'
        '"max_risk":"high","steps":[{"name":"go"}]}\n```'
    )
    assert d["name"] == "x" and d["allow_tools"] == ["a", "b"]
    assert d["deny_tools"] == ["shell"] and d["max_risk"] == "high"
    assert d["workflow"] == [{"name": "go", "instruction": "", "tools": [], "gate": None}]


def test_parse_playbook_rejects_unusable():
    from maverick_dashboard.workflow_ai import parse_playbook
    with pytest.raises(ValueError):
        parse_playbook("not json at all")
    with pytest.raises(ValueError):
        parse_playbook('{"name": "x", "steps": []}')   # no steps -> unusable


def test_draft_playbook_uses_injected_complete_under_cap():
    from maverick_dashboard import workflow_ai

    seen = {}

    class _Resp:
        text = '{"name":"clerk","allow_tools":["t"],"max_risk":"low","steps":[{"name":"do it"}]}'

    def fake_complete(*, system, messages, budget, max_tokens, model):
        seen["system"] = system
        seen["budget"] = budget
        return _Resp()

    d = workflow_ai.draft_playbook("an AP clerk", complete=fake_complete)
    assert d["form"] == "playbook" and d["name"] == "clerk"
    assert seen["budget"].max_dollars == workflow_ai.DRAFT_MAX_DOLLARS
    assert "AGENT PLAYBOOKS" in seen["system"]


# --- refine (iterate on an existing draft) ----------------------------------

def test_build_refine_prompt_includes_current_and_instruction():
    from maverick_dashboard.workflow_ai import build_refine_prompt
    p = build_refine_prompt({"title": "Weekly report", "params": ["topic"]}, "make it daily")
    assert "Weekly report" in p and "make it daily" in p
    assert "COMPLETE" in p  # asks for a full revision, not a diff


def test_refine_workflow_revises_under_cap():
    from maverick_dashboard import workflow_ai
    seen = {}

    class _Resp:
        text = '{"name":"r","title":"R","steps":["a","email the team"]}'

    def fake_complete(*, system, messages, budget, max_tokens, model):
        seen["system"] = system
        seen["budget"] = budget
        seen["content"] = messages[0]["content"]
        return _Resp()

    d = workflow_ai.refine_workflow(
        {"title": "R", "body": "## Steps\n1. a"}, "add a step to email the team",
        complete=fake_complete,
    )
    assert d["steps"] == ["a", "email the team"]
    assert seen["budget"].max_dollars == workflow_ai.DRAFT_MAX_DOLLARS
    assert "WORKFLOWS" in seen["system"]                  # same system prompt as drafting
    assert "email the team" in seen["content"]            # instruction reached the model


def test_refine_playbook_uses_playbook_parser():
    from maverick_dashboard import workflow_ai

    class _Resp:
        text = ('{"name":"bot","allow_tools":["pay"],"max_risk":"high",'
                '"steps":[{"name":"Pay","gate":"approval"}]}')

    d = workflow_ai.refine_playbook({"name": "bot"}, "require approval before paying",
                                    complete=lambda **k: _Resp())
    assert d["form"] == "playbook"
    assert d["workflow"][0]["gate"] == "approval" and d["max_risk"] == "high"


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


def _stub_playbook(monkeypatch, draft):
    from maverick_dashboard import workflow_ai
    monkeypatch.setattr(workflow_ai, "draft_playbook", lambda *a, **k: draft)


_PB_DRAFT = {
    "form": "playbook", "name": "ap-bot", "description": "AP clerk",
    "persona": "You are careful.", "allow_tools": ["ocr_read", "send_payment"],
    "deny_tools": ["shell"], "max_risk": "medium",
    "workflow": [
        {"name": "Read", "instruction": "ocr", "tools": ["ocr_read"], "gate": None},
        {"name": "Pay", "instruction": "pay", "tools": ["send_payment"], "gate": "approval"},
    ],
}


def test_draft_endpoint_form_playbook_routes_to_playbook(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _provider(monkeypatch, True)
    _stub_playbook(monkeypatch, _PB_DRAFT)
    r = _client().post("/api/v1/workflows/draft",
                       json={"description": "an AP clerk", "form": "playbook"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["form"] == "playbook"
    assert body["workflow"][1]["gate"] == "approval"


def test_draft_endpoint_defaults_to_template_form(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _provider(monkeypatch, True)
    # No `form` field at all -> the template drafter, unchanged.
    _stub_draft(monkeypatch, {"name": "t", "title": "T", "params": [],
                              "steps": ["s"], "body": "b", "budget_dollars": 5.0})
    r = _client().post("/api/v1/workflows/draft", json={"description": "x"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "t"


def test_draft_from_file_form_playbook(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _provider(monkeypatch, True)
    captured = {}
    from maverick_dashboard import workflow_ai

    def fake(brief="", source_text="", **k):
        captured["src"] = source_text
        return _PB_DRAFT

    monkeypatch.setattr(workflow_ai, "draft_playbook", fake)
    r = _client().post(
        "/api/v1/workflows/draft-from-file",
        files={"file": ("runbook.md", b"An AP invoice runbook", "text/markdown")},
        data={"form": "playbook"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["form"] == "playbook"
    assert "ap invoice" in captured["src"].lower()


def test_save_playbook_via_agent_override_round_trips(monkeypatch, tmp_path):
    """The playbook form persists through the existing /agents/<name>/override
    path: a new pack, discoverable, with its gated workflow intact."""
    _isolate(monkeypatch, tmp_path)
    r = _client().post("/api/v1/agents/ap-bot/override", json={
        "description": "AP clerk", "persona": "You are a careful AP clerk.",
        "allow_tools": ["ocr_read", "send_payment"], "deny_tools": ["shell"],
        "max_risk": "medium",
        "workflow": [
            {"name": "Read", "instruction": "ocr", "tools": ["ocr_read"], "gate": None},
            {"name": "Pay", "instruction": "pay", "tools": ["send_payment"], "gate": "approval"},
        ],
    })
    assert r.status_code == 200, r.text
    from maverick.domain import available_domains
    prof = available_domains()["ap-bot"]
    assert [(s.name, s.gate) for s in prof.workflow] == [("Read", None), ("Pay", "approval")]
    assert prof.allow_tools == ["ocr_read", "send_payment"]


def test_save_playbook_rejects_lint_failure(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    # An empty allowlist grants ALL tools -> lint error -> write refused (422).
    r = _client().post("/api/v1/agents/loose-bot/override", json={
        "description": "x", "allow_tools": [], "max_risk": "low",
        "workflow": [{"name": "go"}],
    })
    assert r.status_code == 422, r.text
    assert "allow_tools" in r.json()["detail"]


def test_refine_endpoint_routes_by_form(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _provider(monkeypatch, True)
    from maverick_dashboard import workflow_ai
    monkeypatch.setattr(workflow_ai, "refine_workflow",
                        lambda cur, instr: {"name": "t", "title": "T", "params": [],
                                            "steps": ["s"], "body": "b", "budget_dollars": 5.0})
    monkeypatch.setattr(workflow_ai, "refine_playbook", lambda cur, instr: _PB_DRAFT)
    rt = _client().post("/api/v1/workflows/refine",
                        json={"form": "template", "instruction": "make it weekly", "current": {}})
    assert rt.status_code == 200 and rt.json()["name"] == "t"
    rp = _client().post("/api/v1/workflows/refine",
                        json={"form": "playbook", "instruction": "require approval", "current": {}})
    assert rp.status_code == 200 and rp.json()["form"] == "playbook"


def test_refine_endpoint_requires_an_instruction(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _provider(monkeypatch, True)
    r = _client().post("/api/v1/workflows/refine", json={"instruction": "   ", "current": {}})
    assert r.status_code == 400


def test_refine_endpoint_needs_provider_key(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _provider(monkeypatch, False)
    r = _client().post("/api/v1/workflows/refine", json={"instruction": "x", "current": {}})
    assert r.status_code == 400
    assert "provider" in r.json()["detail"].lower()


def test_tools_endpoint_includes_risk(monkeypatch, tmp_path):
    """The connector picker reads /api/v1/tools; each entry carries a risk level."""
    _isolate(monkeypatch, tmp_path)
    r = _client().get("/api/v1/tools")
    assert r.status_code == 200, r.text
    tools = r.json()["tools"]
    assert tools and all("name" in t and "risk" in t for t in tools)
    assert {t["risk"] for t in tools} <= {"low", "medium", "high"}
    by_name = {t["name"]: t for t in tools}
    if "shell" in by_name:                 # a known-high tool is classified high
        assert by_name["shell"]["risk"] == "high"


def test_workflow_builder_page_renders(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = _client().get("/workflow-builder")
    assert r.status_code == 200
    assert '<h1 class="page-title">Workflow builder</h1>' in r.text
    assert 'id="wf-draft-btn"' in r.text
    assert "/api/v1/workflows/draft" in r.text
    # Both forms are offered, and the playbook saves via the agent-override path.
    assert 'id="wf-form-playbook"' in r.text and 'id="pb-preview"' in r.text
    assert "/api/v1/agents/" in r.text
    # Level-100 affordances: refine loop, live governance check, starter examples.
    assert "/api/v1/workflows/refine" in r.text
    assert 'id="pb-refine"' in r.text and 'id="wf-refine"' in r.text
    assert 'id="pb-govern"' in r.text and "/api/v1/agents/" in r.text
    assert 'id="wf-examples"' in r.text
    # Connector picker: browse real tools (with risk) instead of typing names.
    assert 'id="tool-picker"' in r.text and "/api/v1/tools" in r.text
    assert 'data-browse="allow"' in r.text and 'data-browse="deny"' in r.text
    # Visual flow canvas: start/end nodes bracket the connected, gated steps.
    assert "pb-flow__start" in r.text and 'id="pb-flow-end"' in r.text
    # Schedule panel: arm a saved template on a cron (feature defaults on).
    assert 'id="wf-sched"' in r.text and "/api/v1/schedules" in r.text
    # Schedules fire in UTC: the time field labels it + a local-time hint exists.
    assert "Time (UTC)" in r.text and 'id="sched-local-hint"' in r.text
    # Webhook-trigger panel: bind a saved template to an inbound webhook.
    assert 'id="wf-trig"' in r.text and "/api/v1/triggers" in r.text
    # Decluttered: the automate panels are collapsible <details>, not always-open.
    assert '<details class="wf__sched" id="wf-sched"' in r.text
    assert '<summary class="wf__sched-title">' in r.text
    # Reachable from the primary nav (Operate group).
    assert '<span class="nav-label">Workflows</span>' in r.text


def test_p0_council_fixes_builder(monkeypatch, tmp_path):
    # Design-council P0 fixes on the builder page.
    _isolate(monkeypatch, tmp_path)
    t = _client().get("/workflow-builder").text
    assert 'role="heading" aria-level="3"' in t      # <summary> regained heading semantics
    assert "shifts with daylight saving" in t          # UTC->local hint is DST-honest
    assert "label.htmlFor" in t                        # param inputs associate their label


def test_builder_prefill_deeplink_jumps_to_automate(monkeypatch, tmp_path):
    # ?template=<name> injects a prefill so the JS jumps straight to automating
    # an existing template (reusing the schedule/trigger panels), not the draft flow.
    _isolate(monkeypatch, tmp_path)
    tdir = tmp_path / ".maverick" / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "weekly-report.md").write_text(
        "---\ntitle: Weekly report\nparams:\n  - topic\n---\nbody\n", encoding="utf-8")
    r = _client().get("/workflow-builder?template=weekly-report")
    assert r.status_code == 200
    assert "weekly-report" in r.text and "WF_PREFILL = null" not in r.text
    # an unknown template (and no query) yields no prefill; the page still renders
    assert "WF_PREFILL = null" in _client().get("/workflow-builder?template=nope").text
    assert "WF_PREFILL = null" in _client().get("/workflow-builder").text
