"""Per-principal session/bearer revocation (#58): revoke_principal bumps a
monotonic epoch; any credential whose iat predates it is rejected."""
from __future__ import annotations

import pytest
from maverick_dashboard import session_revocation as sr


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))


def test_unrevoked_principal_allows_everything():
    assert sr.revocation_epoch("alice") == 0.0
    assert sr.is_revoked("alice", issued_at=1.0) is False
    assert sr.is_revoked("alice", issued_at=None) is False


def test_revoke_rejects_older_allows_newer():
    sr.revoke_principal("bob", at=100.0)
    assert sr.revocation_epoch("bob") == 100.0
    assert sr.is_revoked("bob", issued_at=99.0) is True       # issued before epoch
    assert sr.is_revoked("bob", issued_at=100.0) is False     # at/after epoch is ok
    assert sr.is_revoked("bob", issued_at=None) is True       # no iat under epoch -> revoked


def test_epoch_is_monotonic():
    sr.revoke_principal("carol", at=200.0)
    sr.revoke_principal("carol", at=150.0)  # stale write -> must not move backwards
    assert sr.revocation_epoch("carol") == 200.0


def test_blank_principal_is_noop():
    sr.revoke_principal("")
    assert sr.revocation_epoch("") == 0.0


def test_garbage_iat_treated_as_revoked():
    sr.revoke_principal("dave", at=100.0)
    assert sr.is_revoked("dave", issued_at="not-a-number") is True
