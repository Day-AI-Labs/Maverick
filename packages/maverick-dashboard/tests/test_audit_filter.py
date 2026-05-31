"""The /audit page supports a ?kind= filter that narrows the tail to one
event kind, with a dropdown of the kinds present in the tail."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _tmp_audit(monkeypatch, tmp_path):
    import maverick.audit as audit
    from maverick.audit.writer import AuditLog
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    log = AuditLog(tmp_path / "audit")
    monkeypatch.setattr(audit, "default_audit_log", lambda: log)
    return log


def _ev(log, kind, **payload):
    from maverick.audit.events import AuditEvent
    log.record(AuditEvent(ts=time.time(), kind=kind, payload=payload))


def test_audit_page_lists_kinds_and_filters(monkeypatch, tmp_path):
    log = _tmp_audit(monkeypatch, tmp_path)
    _ev(log, "tool_call", name="shell", input_summary="ls -la")
    _ev(log, "shield_block", stage="input", reason="jailbreak attempt")
    _ev(log, "tool_call", name="read_file", input_summary="config")

    client = _client()

    # Unfiltered: both kinds present and the filter dropdown exists.
    body = client.get("/audit").text
    assert body.count("shield_block") >= 1
    assert 'name="kind"' in body  # the dropdown

    # Filtered to shield_block: the tool_call events are gone.
    filtered = client.get("/audit?kind=shield_block").text
    assert "jailbreak attempt" in filtered
    assert "input_summary" not in filtered  # tool_call rows filtered out


def test_audit_unknown_kind_yields_no_rows(monkeypatch, tmp_path):
    log = _tmp_audit(monkeypatch, tmp_path)
    _ev(log, "tool_call", name="shell", input_summary="ls")

    r = _client().get("/audit?kind=does_not_exist")
    assert r.status_code == 200
    assert "input_summary" not in r.text  # no matching events
