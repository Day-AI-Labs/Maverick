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
