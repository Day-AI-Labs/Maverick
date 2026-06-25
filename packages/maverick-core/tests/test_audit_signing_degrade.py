"""Audit signing must FAIL CLOSED under a compliance floor when the `cryptography`
extra is missing -- it must never silently write unsigned rows while an operator
believes HIPAA-mode tamper-evidence is active (purchase-blocker audit #55). With
no floor it still degrades, but loudly (error, not a swallowed warning)."""
from __future__ import annotations

import logging

import maverick.audit.signing as signing
import maverick.audit.writer as writer
import maverick.compliance_profiles as compliance_profiles
import pytest
from maverick.audit.events import AuditEvent


def _force_missing_crypto(monkeypatch):
    """Make AuditSigner construction raise ImportError, as if `cryptography`
    (the audit-signing extra) were not installed."""
    def _boom(_path):
        raise ImportError("cryptography not installed")
    monkeypatch.setattr(signing, "AuditSigner", _boom)


def _event() -> AuditEvent:
    return AuditEvent(ts=1.0, kind="goal_start", agent="t", goal_id=None, payload={})


def test_degrade_is_loud_without_a_compliance_floor(tmp_path, monkeypatch, caplog):
    _force_missing_crypto(monkeypatch)
    monkeypatch.setattr(compliance_profiles, "requires_floor", lambda _floor: False)
    # Force signing on (the test suite disables secure-by-default via conftest).
    log = writer.AuditLog(tmp_path / "audit", sign=True)
    with caplog.at_level(logging.ERROR):
        ok = log.record(_event())
    assert ok is True  # no floor -> degrade gracefully to unsigned
    assert any(r.levelno >= logging.ERROR and "UNSIGNED" in r.getMessage()
               for r in caplog.records), "degrade must log at ERROR, not be silent"


def test_refuses_to_write_unsigned_under_a_compliance_floor(tmp_path, monkeypatch):
    _force_missing_crypto(monkeypatch)
    monkeypatch.setattr(compliance_profiles, "requires_floor", lambda _floor: True)
    log = writer.AuditLog(tmp_path / "audit")
    with pytest.raises(RuntimeError, match="refusing to write UNSIGNED"):
        log.record(_event())
