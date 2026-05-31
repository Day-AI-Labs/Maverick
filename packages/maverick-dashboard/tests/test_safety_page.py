"""Safety dashboard page: surfaces shield_block audit events (what the
shield denied), aggregated by stage and reason."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _tmp_audit(monkeypatch, tmp_path):
    """Point the dashboard's audit reader at a tmp log; return it."""
    import maverick.audit as audit
    from maverick.audit.writer import AuditLog
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    log = AuditLog(tmp_path / "audit")
    monkeypatch.setattr(audit, "default_audit_log", lambda: log)
    return log


def _block(log, *, stage, reason, score=None):
    from maverick.audit.events import AuditEvent
    log.record(AuditEvent(
        ts=time.time(), kind="shield_block",
        payload={"stage": stage, "reason": reason, "score": score},
    ))


def test_safety_page_empty(monkeypatch, tmp_path):
    _tmp_audit(monkeypatch, tmp_path)
    r = _client().get("/safety")
    assert r.status_code == 200
    assert "No shield blocks" in r.text


def test_safety_page_aggregates_blocks(monkeypatch, tmp_path):
    log = _tmp_audit(monkeypatch, tmp_path)
    _block(log, stage="input", reason="prompt injection", score=0.95)
    _block(log, stage="tool", reason="prompt injection", score=0.80)
    _block(log, stage="output", reason="secret exfiltration", score=None)

    r = _client().get("/safety")
    assert r.status_code == 200
    body = r.text
    assert "prompt injection" in body
    assert "secret exfiltration" in body
    assert "0.95" in body                       # score formatted
    assert "input" in body and "output" in body  # stage breakdown


def test_safety_page_ignores_non_shield_events(monkeypatch, tmp_path):
    log = _tmp_audit(monkeypatch, tmp_path)
    from maverick.audit.events import AuditEvent
    log.record(AuditEvent(ts=time.time(), kind="tool_call",
                          payload={"name": "shell", "input_summary": "ls -la"}))
    _block(log, stage="input", reason="jailbreak", score=0.7)

    body = _client().get("/safety").text
    assert "jailbreak" in body
    assert "input_summary" not in body  # unrelated event content must not leak


def test_safety_link_in_nav(monkeypatch, tmp_path):
    _tmp_audit(monkeypatch, tmp_path)
    r = _client().get("/safety")
    assert r.status_code == 200
    assert 'href="/safety"' in r.text
