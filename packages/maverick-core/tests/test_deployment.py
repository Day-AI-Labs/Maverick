"""Regulated-deployment golden path: prove the data-boundary guarantees hold.

The end-to-end proof for the reference profile (enterprise mode + audit signing
+ retention): a bare deployment fails every boundary guarantee, and the profile
makes the verifier pass, seals real data on disk, and zeroes out
``maverick compliance --strict``.
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3

import pytest

requires_crypto = pytest.mark.skipif(
    importlib.util.find_spec("cryptography") is None,
    reason="cryptography extra is not installed",
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    for var in (
        "MAVERICK_ENTERPRISE", "MAVERICK_ENCRYPT_AT_REST", "MAVERICK_ENCRYPTION_KEY",
        "MAVERICK_AUDIT_SIGN", "MAVERICK_CONSENT_MODE", "MAVERICK_AI_DISCLOSURE",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})
    # Keep generated at-rest/audit keys and audit probe files off the real home dir.
    from maverick import crypto_at_rest as car
    from maverick import paths
    from maverick.audit import signing

    monkeypatch.setattr(paths, "maverick_home", lambda: tmp_path / "home")
    monkeypatch.setattr(signing, "KEY_DIR", signing._LEGACY_KEY_DIR)
    monkeypatch.setattr(car, "_KEY_PATH", tmp_path / "keys" / "at_rest.key")


def test_bare_deployment_fails_the_boundary_guarantees():
    from maverick.deployment import all_passed, verify_deployment

    checks = {c.name: c for c in verify_deployment()}
    assert not all_passed(list(checks.values()))
    # The two load-bearing, actively-probed guarantees are off by default.
    assert checks["Egress lock"].passed is False
    assert checks["At-rest encryption"].passed is False


@requires_crypto
def test_verifier_fails_when_audit_signing_key_cannot_initialize(monkeypatch):
    from maverick.deployment import verify_deployment
    from maverick.paths import data_dir

    monkeypatch.setenv("MAVERICK_AUDIT_SIGN", "1")

    key_dir = data_dir("audit", "keys")
    key_dir.mkdir(parents=True)
    key_id = "0123456789abcdef"
    (key_dir / f"{key_id}.key").write_bytes(b"bad")
    (key_dir / f"{key_id}.pub").write_bytes(b"also-bad")
    # Ensure the malformed key is selected as the newest available keypair.
    newest_mtime = 2_000_000_000
    os.utime(key_dir / f"{key_id}.key", (newest_mtime, newest_mtime))

    checks = {c.name: c for c in verify_deployment()}

    assert checks["Tamper-evident audit"].passed is False
    assert "audit signing probe failed" in checks["Tamper-evident audit"].detail


@requires_crypto
def test_regulated_profile_passes_seals_data_and_is_compliant(monkeypatch, tmp_path):
    from maverick.compliance import compliance_report
    from maverick.deployment import all_passed, verify_deployment
    from maverick.world_model import WorldModel

    # The reference profile, expressed as env (the config-file form is documented
    # in docs/regulated-deployment.md). Enterprise mode implies at-rest encryption.
    monkeypatch.setenv("MAVERICK_ENTERPRISE", "1")
    monkeypatch.setenv("MAVERICK_AUDIT_SIGN", "1")
    monkeypatch.setattr(
        "maverick.config.load_config",
        lambda *a, **k: {"retention": {"audit_days": 365}},
    )

    # Every boundary guarantee holds (the dict comprehension surfaces details on
    # failure so a regression names which guarantee broke).
    checks = {c.name: c for c in verify_deployment()}
    assert all_passed(list(checks.values())), {n: c.detail for n, c in checks.items()}

    # It is real, not just flags: data written through the normal world-model path
    # is ciphertext on disk, yet reads back transparently.
    db = tmp_path / "world.db"
    wm = WorldModel(db)
    conv = wm.get_or_create_conversation("slack", "u")
    wm.append_turn(conv.id, "user", "patient SSN 123-45-6789")
    raw = sqlite3.connect(str(db)).execute("SELECT content FROM turns").fetchone()[0]
    assert raw.startswith("MVKAR1:") and "123-45-6789" not in raw
    assert wm.recent_turns(conv.id)[-1].content == "patient SSN 123-45-6789"

    # The same profile makes `maverick compliance --strict` green.
    assert [c.control for c in compliance_report() if c.status == "action_needed"] == []
