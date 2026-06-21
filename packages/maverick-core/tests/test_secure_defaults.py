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


def test_at_rest_encryption_on_by_default(secure, monkeypatch, tmp_path):
    monkeypatch.delenv("MAVERICK_ENCRYPT_AT_REST", raising=False)
    from maverick import crypto_at_rest as car
    monkeypatch.setattr(car, "_KEY_PATH", tmp_path / "keys" / "at_rest.key")
    assert car.at_rest_enabled() is True
    # Zero-config round-trip: the key auto-generates and seal->unseal restores.
    sealed = car.seal_to_str("PHI: patient record")
    assert sealed != "PHI: patient record"          # actually sealed
    assert car.unseal_from_str(sealed) == "PHI: patient record"


def test_at_rest_reads_are_plaintext_tolerant(secure, monkeypatch, tmp_path):
    # Existing plaintext (written before the flip) still reads back unchanged.
    from maverick import crypto_at_rest as car
    monkeypatch.setattr(car, "_KEY_PATH", tmp_path / "keys" / "at_rest.key")
    assert car.unseal_from_str("legacy plaintext value") == "legacy plaintext value"


def test_at_rest_explicit_off_wins(secure, monkeypatch):
    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "0")
    from maverick import crypto_at_rest as car
    assert car.at_rest_enabled() is False
