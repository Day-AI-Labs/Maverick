"""Env-injected audit signing key (enterprise key custody, H29).

When ``MAVERICK_AUDIT_SIGNING_KEY`` holds a raw Ed25519 private key, that key is
the active audit signer and is held in memory only -- never written to the local
key dir -- so the chain's trust anchor can live in a KMS / secrets manager and be
injected at deploy time. Only the public half (+ an ``.injected`` marker) is
persisted, so local ``verify_chain`` still trusts the chain.
"""
from __future__ import annotations

import pytest
from maverick.audit import signing


@pytest.fixture(autouse=True)
def _temp_keys(tmp_path, monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setattr(signing, "KEY_DIR", tmp_path / "keys")
    monkeypatch.delenv(signing._SIGNING_KEY_ENV, raising=False)
    yield


def _fresh_key_hex() -> tuple[str, bytes]:
    """A raw 32-byte Ed25519 private key as hex, plus its raw bytes."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    priv = ed25519.Ed25519PrivateKey.generate()
    raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return raw.hex(), raw


def test_injected_key_signs_without_writing_private_to_disk(monkeypatch):
    key_hex, _ = _fresh_key_hex()
    monkeypatch.setenv(signing._SIGNING_KEY_ENV, key_hex)

    priv, pub, key_id = signing._load_or_create_keypair()
    key_dir = signing._key_dir()

    # The private key is NEVER persisted; only the public half + marker are.
    assert not (key_dir / f"{key_id}.key").exists()
    assert (key_dir / f"{key_id}.pub").exists()
    assert (key_dir / f"{key_id}.injected").exists()
    # key_id is the deterministic fingerprint of the public key.
    import hashlib
    assert key_id == hashlib.sha256(pub).hexdigest()[:16]


def test_injected_key_chain_verifies_via_marker(tmp_path, monkeypatch):
    key_hex, _ = _fresh_key_hex()
    monkeypatch.setenv(signing._SIGNING_KEY_ENV, key_hex)

    audit = tmp_path / "2026-06-20.ndjson"
    s = signing.AuditSigner(audit)
    s.write({"event": "first"})
    s.write({"event": "second"})

    # The private .key is absent, but the .injected marker lets local verify
    # trust the lone .pub -- so the chain verifies clean.
    assert signing.verify_chain(audit) == []


def test_injected_key_accepts_base64(monkeypatch):
    import base64

    _, raw = _fresh_key_hex()
    monkeypatch.setenv(signing._SIGNING_KEY_ENV, base64.b64encode(raw).decode())
    _, _, key_id = signing._load_or_create_keypair()
    assert signing._is_valid_key_id(key_id)


def test_injected_key_precedence_over_on_disk(monkeypatch):
    # An on-disk key exists first...
    _, _, disk_id = signing._load_or_create_keypair()
    # ...then an injected key is provided: it must win.
    key_hex, _ = _fresh_key_hex()
    monkeypatch.setenv(signing._SIGNING_KEY_ENV, key_hex)
    _, _, active_id = signing._load_or_create_keypair()
    assert active_id != disk_id
    assert (signing._key_dir() / f"{active_id}.injected").exists()


def test_malformed_injected_key_falls_back_to_disk(monkeypatch):
    monkeypatch.setenv(signing._SIGNING_KEY_ENV, "not-a-valid-key")
    # Falls back to generating/loading an on-disk key (private .key present).
    _, _, key_id = signing._load_or_create_keypair()
    assert (signing._key_dir() / f"{key_id}.key").exists()
    assert not (signing._key_dir() / f"{key_id}.injected").exists()


def test_decode_injected_key_rejects_wrong_length(monkeypatch):
    # 16 bytes of hex -> not a 32-byte Ed25519 key.
    assert signing._decode_injected_key("00" * 16) is None
    assert signing._decode_injected_key("") is None
    # A valid 32-byte hex round-trips.
    _, raw = _fresh_key_hex()
    assert signing._decode_injected_key(raw.hex()) == raw
