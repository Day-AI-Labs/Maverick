"""Operator mission-control (/oversight).

Unifies every control-plane intervention — governance holds, shield blocks,
capability + egress denials, consent denials, killswitch halts — into one
operator pane, alongside live halt state, pending approvals, and active agents.

Hermetic like the other dashboard tests: OIDC off (``require_principal``
returns None), HOME/MAVERICK_HOME isolated so the audit log + HALT file land in
tmp, and the WorldModel points at a fresh DB.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    # Use a fresh audit writer pinned at the isolated HOME so record() and the
    # page read the same log.
    import maverick.audit.writer as aw
    aw._default = None


def test_oversight_page_renders_and_nav_link(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = _client().get("/oversight")
    assert r.status_code == 200
    assert "oversight" in r.text.lower()
    # Nav link is wired into the primary menu.
    assert 'href="/oversight"' in r.text
    assert ">Oversight<" in r.text


def test_unifies_every_guardrail(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick.audit import record
    record("governance_denied", agent="acme.coder", tool="shell",
           rule="require_human_actions", reason="'shell' requires human approval")
    record("shield_block", agent="acme.coder", stage="tool", reason="prompt injection")
    record("capability_denied", agent="acme.coder", tool="s3", principal="agent:acme.coder")
    record("egress_blocked", agent="acme.coder", provider="openai")

    text = _client().get("/oversight").text
    # Every guardrail's events surface in one pane (the gap: capability + egress
    # had no aggregated view before).
    for kind in ("governance_denied", "shield_block", "capability_denied", "egress_blocked"):
        assert kind in text
    # And their key details render.
    assert "require_human_actions" in text
    assert "prompt injection" in text
    assert "s3" in text
    assert "openai" in text


def test_consent_approve_excluded_deny_counted(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick.audit import record
    record("consent_result", agent="a", decision="approve", action="deploy")
    record("consent_result", agent="a", decision="deny", action="rm -rf /")
    text = _client().get("/oversight").text
    # A denial is an intervention; an approval is not.
    assert "rm -rf /" in text
    assert "deploy" not in text


def test_non_intervention_events_excluded(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick.audit import record
    record("tool_call", agent="a", name="read_file", input_summary="x")
    text = _client().get("/oversight").text
    # Ordinary activity isn't an intervention -> empty state.
    assert "No control-plane interventions" in text


def test_halt_state_reflected(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import maverick.killswitch as ks
    ks.clear()  # no in-process latch
    # The HALT file stat is cached for 1s; reset the cache marker before each
    # read so it re-stats the isolated file. (base.html's halt-pill JS always
    # contains "HALTED. Click to resume.", so assert on the template marker.)
    ks._last_file_check_ts = 0.0
    assert "<strong>HALTED</strong>" not in _client().get("/oversight").text
    # Arm the killswitch (the same HALT file the nav pill / api toggle uses).
    p = ks._halt_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("test halt", encoding="utf-8")
    ks._last_file_check_ts = 0.0
    assert "<strong>HALTED</strong>" in _client().get("/oversight").text


def test_pending_holds_are_actionable_inline(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick.world_model import WorldModel
    w = WorldModel(tmp_path / "world.db")
    w.create_approval("shell", risk="high", detail="'shell' requires human approval")
    text = _client().get("/oversight").text
    assert 'href="/approvals"' in text          # still links to the full queue
    # ...but the hold is also actionable right here: the action + inline
    # approve/deny buttons wired to the decision API render on the console.
    assert "shell" in text
    assert 'data-action="approve"' in text
    assert 'data-action="deny"' in text
    assert "/api/v1/approvals/" in text
    # Governance REQUIRE_HUMAN holds are labelled (EU AI Act Art 14).
    assert "Art 14" in text


def test_no_pending_holds_shows_empty_state(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    text = _client().get("/oversight").text
    assert "No pending approvals." in text


def test_day_traversal_is_neutralized(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = _client().get("/oversight?day=../../../etc/passwd")
    assert r.status_code == 200  # safe_audit_day collapses it; no 500, no escape
    assert "../../../etc/passwd" not in r.text


# --- live "Active now" panel ------------------------------------------------

def test_active_endpoint_lists_running_agents(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick.world_model import WorldModel
    w = WorldModel(tmp_path / "world.db")
    gid = w.create_goal("ship the thing", "do it")
    w.set_goal_status(gid, "active")
    w.append_event(gid, "coder", "tool_call", "shell: ls -la")
    body = _client().get("/api/v1/oversight/active").json()
    g = next((x for x in body["goals"] if x["id"] == gid), None)
    assert g is not None
    assert g["title"] == "ship the thing"
    assert "shell" in g["activity"]  # latest event surfaces as current activity


def test_active_endpoint_excludes_finished_goals(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick.world_model import WorldModel
    w = WorldModel(tmp_path / "world.db")
    done = w.create_goal("old", "x")
    w.set_goal_status(done, "done")
    running = w.create_goal("now", "y")
    w.set_goal_status(running, "active")
    ids = {g["id"] for g in _client().get("/api/v1/oversight/active").json()["goals"]}
    assert running in ids
    assert done not in ids


def test_oversight_page_has_live_active_panel(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    text = _client().get("/oversight").text
    assert 'id="active-now"' in text
    assert "/api/v1/oversight/active" in text  # the client polls this endpoint


# --- multi-day (incident-review) range --------------------------------------

def _write_event_on_day(audit_dir, day, kind, **payload):
    """Append one raw audit event to a specific day-file (the writer only ever
    names by *today*, so multi-day fixtures are written directly)."""
    import json
    audit_dir.mkdir(parents=True, exist_ok=True)
    ev = {"v": 1, "ts": 1_000_000.0, "kind": kind, "agent": "a", "goal_id": 1, **payload}
    with open(audit_dir / f"{day}.ndjson", "a", encoding="utf-8") as f:
        f.write(json.dumps(ev) + "\n")


def test_multiday_range_spans_day_files(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick.paths import data_dir
    audit_dir = data_dir("audit")
    _write_event_on_day(audit_dir, "2026-01-10", "governance_denied",
                        reason="jan-hold", rule="r")
    _write_event_on_day(audit_dir, "2026-02-20", "shield_block",
                        stage="tool", reason="feb-block")
    _write_event_on_day(audit_dir, "2026-03-30", "capability_denied",
                        tool="s3outofrange")  # outside the window
    text = _client().get("/oversight?since=2026-01-01&until=2026-02-28").text
    assert "jan-hold" in text                  # in range (Jan day-file)
    assert "feb-block" in text                 # in range (Feb day-file)
    assert "s3outofrange" not in text          # March is outside [since, until]
    assert "2026-01-01" in text and "2026-02-28" in text  # range shown in label


def test_multiday_range_uses_bounded_export_reader(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import maverick.audit.export as export
    import maverick_dashboard.app as app_mod

    captured = {}

    def fake_iter_audit_events(**kwargs):
        captured.update(kwargs)
        yield {
            "kind": "shield_block",
            "stage": "tool",
            "reason": "bounded-reader",
        }

    monkeypatch.setattr(export, "iter_audit_events", fake_iter_audit_events)

    text = _client().get("/oversight?since=2026-01-01").text

    assert "bounded-reader" in text
    assert captured["max_events"] == app_mod._OVERSIGHT_RANGE_MAX_EVENTS
    assert captured["max_bytes"] == app_mod._OVERSIGHT_RANGE_MAX_BYTES
    assert captured["max_files"] == app_mod._OVERSIGHT_RANGE_MAX_FILES

def test_range_inputs_present(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    text = _client().get("/oversight").text
    assert 'name="since"' in text
    assert 'name="until"' in text


def test_range_day_traversal_neutralized(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = _client().get("/oversight?since=../../etc&until=../../passwd")
    assert r.status_code == 200  # safe_audit_day collapses bad bounds -> open
    # The crafted values are neutralized to None (empty inputs), never echoed
    # back or used as a path component.
    assert "../../etc" not in r.text
    assert "../../passwd" not in r.text
