"""Audit signing-key rotation.

Rotation is safe and additive: the new key becomes the active signer while every
prior public key is retained, so the chain stays verifiable across the rotation
(each row carries its key_id). No audit data is rewritten.
"""
from __future__ import annotations

import os

import pytest
from maverick.audit import signing


@pytest.fixture(autouse=True)
def _temp_keys(tmp_path, monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setattr(signing, "KEY_DIR", tmp_path / "keys")
    yield


def test_rotation_mints_new_active_key_and_keeps_old():
    # Initial key.
    _, _, kid_a = signing._load_or_create_keypair()
    # Rotate.
    kid_b = signing.rotate_audit_keypair()
    assert kid_b != kid_a

    key_dir = signing._key_dir()
    # Both public keys retained (old still verifies old rows).
    assert (key_dir / f"{kid_a}.pub").exists()
    assert (key_dir / f"{kid_b}.pub").exists()

    # Make the new key unambiguously newest, then confirm it is now active.
    os.utime(key_dir / f"{kid_b}.key", None)
    _, _, active = signing._load_or_create_keypair()
    assert active == kid_b


def test_chain_verifies_across_rotation(tmp_path):
    # Sign a couple of rows, rotate, sign more, and verify the whole file.
    audit = tmp_path / "2026-06-18.ndjson"
    s1 = signing.AuditSigner(audit)
    s1.write({"event": "first"})
    s1.write({"event": "second"})

    signing.rotate_audit_keypair()
    key_dir = signing._key_dir()
    # Ensure the rotated key is newest so a fresh signer adopts it.
    newest = max(key_dir.glob("*.key"), key=lambda p: p.stat().st_mtime)
    os.utime(newest, None)

    s2 = signing.AuditSigner(audit)
    s2.write({"event": "third"})

    # No chain breaks: old rows verify under the old key, the new row under the
    # rotated key (resolved per-row by key_id). verify_chain returns [] when OK.
    assert signing.verify_chain(audit) == []
