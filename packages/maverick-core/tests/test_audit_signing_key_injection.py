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


# ----- off-host signing enforcement + KMS-wrapped key source (council H5) -----

def test_offhost_not_required_by_default(monkeypatch):
    # No enterprise mode, no flag, no off-host key -> on-disk key is allowed.
    monkeypatch.delenv("MAVERICK_AUDIT_REQUIRE_OFFHOST_KEY", raising=False)
    monkeypatch.delenv(signing._SIGNING_KEY_ENV, raising=False)
    monkeypatch.delenv(signing._KMS_WRAPPED_KEY_ENV, raising=False)
    monkeypatch.setattr(signing, "require_offhost_signing", lambda: False)
    priv, pub, _ = signing._load_or_create_keypair()
    assert len(priv) == 32 and len(pub) == 32


def test_offhost_required_refuses_on_disk_key(monkeypatch):
    monkeypatch.setenv("MAVERICK_AUDIT_REQUIRE_OFFHOST_KEY", "1")
    monkeypatch.delenv(signing._SIGNING_KEY_ENV, raising=False)
    monkeypatch.delenv(signing._KMS_WRAPPED_KEY_ENV, raising=False)
    with pytest.raises(RuntimeError, match="off-host audit signing is required"):
        signing._load_or_create_keypair()


def test_offhost_required_satisfied_by_injected_key(monkeypatch):
    # An env-injected (KMS-sourced) key satisfies the requirement -- no raise.
    monkeypatch.setenv("MAVERICK_AUDIT_REQUIRE_OFFHOST_KEY", "1")
    key_hex, raw = _fresh_key_hex()
    monkeypatch.setenv(signing._SIGNING_KEY_ENV, key_hex)
    priv, pub, _ = signing._load_or_create_keypair()
    assert priv == raw


def test_kms_wrapped_key_source(monkeypatch):
    # A KMS-wrapped blob unwraps (via the configured cloud KMS) into memory.
    import base64
    from unittest import mock
    key32 = bytes(range(32))
    monkeypatch.setenv(signing._KMS_WRAPPED_KEY_ENV, base64.b64encode(b"wrapped").decode())

    class _FakeKEK:
        def unwrap(self, wrapped, *, context=None):
            assert context == b"maverick-audit-signing"
            return key32

    monkeypatch.setattr("maverick.config.load_config", lambda: {"kms": {"provider": "vault"}})
    with mock.patch("maverick.kms_backends.build_cloud_kms", return_value=_FakeKEK()):
        res = signing._kms_wrapped_keypair()
    assert res is not None and res[0] == key32


def test_require_offhost_env_overrides(monkeypatch):
    monkeypatch.setenv("MAVERICK_AUDIT_REQUIRE_OFFHOST_KEY", "on")
    assert signing.require_offhost_signing() is True
    monkeypatch.setenv("MAVERICK_AUDIT_REQUIRE_OFFHOST_KEY", "off")
    assert signing.require_offhost_signing() is False
