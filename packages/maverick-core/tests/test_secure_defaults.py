"""Secure-by-default posture: the hardened controls default ON in production.

The suite-wide conftest pins MAVERICK_SECURE_DEFAULT=0 (legacy posture) so other
tests assert explicit on/off mechanics; these override it to the production
default and verify each control comes up hardened.
"""
from __future__ import annotations

import pytest
from maverick.security_defaults import secure_by_default


@pytest.fixture
def secure(monkeypatch):
    # Unset -> production default (secure). Belt-and-suspenders: also clear the
    # per-control knobs so we observe the DEFAULT, not an explicit override.
    monkeypatch.delenv("MAVERICK_SECURE_DEFAULT", raising=False)
    monkeypatch.delenv("MAVERICK_AUDIT_SIGN", raising=False)
    monkeypatch.setattr("maverick.config.load_config", dict)


def test_secure_by_default_is_on_when_unset(secure):
    assert secure_by_default() is True


def test_secure_by_default_env_off(monkeypatch):
    monkeypatch.setenv("MAVERICK_SECURE_DEFAULT", "0")
    assert secure_by_default() is False
    monkeypatch.setenv("MAVERICK_SECURE_DEFAULT", "1")
    assert secure_by_default() is True


def test_secure_by_default_config_off(monkeypatch):
    monkeypatch.delenv("MAVERICK_SECURE_DEFAULT", raising=False)
    monkeypatch.setattr("maverick.config.load_config",
                        lambda: {"security": {"secure_defaults": False}})
    assert secure_by_default() is False


def test_audit_signing_on_by_default(secure):
    from maverick.audit.writer import _resolve_signing
    assert _resolve_signing(None) is True


def test_audit_signing_explicit_knob_wins(secure, monkeypatch):
    # An operator that explicitly disables signing still wins over the default.
    monkeypatch.setenv("MAVERICK_AUDIT_SIGN", "0")
    from maverick.audit.writer import _resolve_signing
    assert _resolve_signing(None) is False
    # And the explicit arg always wins.
    assert _resolve_signing(False) is False
    assert _resolve_signing(True) is True
