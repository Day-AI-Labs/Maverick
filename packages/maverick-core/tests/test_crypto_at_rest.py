"""Encryption at rest: AES-256-GCM seal/unseal + key management."""
from __future__ import annotations

import base64

import pytest
from maverick import crypto_at_rest as car

# AES-GCM needs the optional 'cryptography' extra; skip (don't fail) where it is
# absent, matching the audit-signing tests (test_audit_anchor.py).
pytest.importorskip("cryptography")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.delenv("MAVERICK_ENCRYPT_AT_REST", raising=False)
    monkeypatch.delenv("MAVERICK_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("MAVERICK_ENTERPRISE", raising=False)
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})
    # Keep the generated key out of the real ~/.maverick.
    monkeypatch.setattr(car, "_KEY_PATH", tmp_path / "keys" / "at_rest.key")


def test_off_by_default():
    assert car.at_rest_enabled() is False


def test_enabled_by_env(monkeypatch):
    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "1")
    assert car.at_rest_enabled() is True
    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "0")
    assert car.at_rest_enabled() is False


def test_implied_by_enterprise(monkeypatch):
    monkeypatch.setenv("MAVERICK_ENTERPRISE", "1")
    assert car.at_rest_enabled() is True


def test_config_enables(monkeypatch):
    monkeypatch.setattr(
        "maverick.config.load_config", lambda *a, **k: {"encryption": {"at_rest": True}}
    )
    assert car.at_rest_enabled() is True


def test_seal_unseal_roundtrip():
    secret = b"patient SSN 123-45-6789"
    blob = car.seal(secret)
    assert car.is_sealed(blob)
    assert blob != secret  # actually encrypted
    assert b"123-45-6789" not in blob  # plaintext not present in ciphertext
    assert car.unseal(blob) == secret


def test_text_helpers():
    blob = car.seal_text("hello — é")
    assert car.unseal_to_text(blob) == "hello — é"


def test_unseal_passthrough_for_plaintext():
    # A blob without the magic header is legacy plaintext -> returned as-is.
    assert car.unseal(b"plain old note") == b"plain old note"
    assert car.is_sealed(b"plain old note") is False


def test_each_seal_uses_fresh_nonce():
    a, b = car.seal(b"same"), car.seal(b"same")
    assert a != b  # nonce randomization -> distinct ciphertexts
    assert car.unseal(a) == car.unseal(b) == b"same"


def test_tamper_is_detected():
    blob = bytearray(car.seal(b"important"))
    blob[-1] ^= 0x01  # flip a tag bit
    with pytest.raises(Exception):  # noqa: B017 - InvalidTag from the AEAD
        car.unseal(bytes(blob))


def test_injected_key_hex_and_base64(monkeypatch):
    key = bytes(range(32))
    monkeypatch.setenv("MAVERICK_ENCRYPTION_KEY", key.hex())
    blob = car.seal(b"x")
    monkeypatch.setenv("MAVERICK_ENCRYPTION_KEY", base64.b64encode(key).decode())
    assert car.unseal(blob) == b"x"  # same key, different encoding -> opens


def test_injected_key_wrong_size_fails(monkeypatch):
    monkeypatch.setenv("MAVERICK_ENCRYPTION_KEY", "00" * 16)  # 16 bytes, not 32
    with pytest.raises(car.EncryptionUnavailable):
        car.seal(b"x")


def test_generated_key_persists_and_chmod(monkeypatch):
    blob = car.seal(b"persist me")
    assert car._KEY_PATH.exists()
    assert (car._KEY_PATH.stat().st_mode & 0o777) == 0o600
    # A second seal reuses the same on-disk key, so unseal still works.
    assert car.unseal(blob) == b"persist me"


def test_memory_tool_seals_on_disk(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "1")
    monkeypatch.setenv("MAVERICK_MEMORY_DIR", str(tmp_path / "mem"))
    from maverick.tools.memory import memory

    tool = memory()
    out = tool.fn({"command": "create", "path": "notes.md",
                   "file_text": "patient SSN 123-45-6789"})
    assert "wrote" in out
    raw = (tmp_path / "mem" / "notes.md").read_bytes()
    assert car.is_sealed(raw)          # on-disk file is ciphertext
    assert b"123-45-6789" not in raw   # plaintext absent on disk
    view = tool.fn({"command": "view", "path": "notes.md"})
    assert "123-45-6789" in view       # view transparently decrypts


def test_memory_reads_legacy_plaintext(monkeypatch, tmp_path):
    memdir = tmp_path / "mem"
    memdir.mkdir()
    (memdir / "old.md").write_text("legacy note", encoding="utf-8")  # pre-encryption
    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "1")
    monkeypatch.setenv("MAVERICK_MEMORY_DIR", str(memdir))
    from maverick.tools.memory import memory

    view = memory().fn({"command": "view", "path": "old.md"})
    assert "legacy note" in view       # transparent plaintext fallback


def test_seal_to_str_roundtrip_and_passthrough():
    tok = car.seal_to_str("hello secret")
    assert tok.startswith("MVKAR1:")
    assert "hello secret" not in tok
    assert car.unseal_from_str(tok) == "hello secret"
    # Legacy plaintext (no marker) passes through unchanged.
    assert car.unseal_from_str("plain value") == "plain value"
    assert car.is_sealed_str(tok) and not car.is_sealed_str("plain value")


def test_world_db_seals_turns_and_facts(monkeypatch, tmp_path):
    import sqlite3

    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "1")
    from maverick.world_model import WorldModel

    db = tmp_path / "world.db"
    wm = WorldModel(db)
    conv = wm.get_or_create_conversation("slack", "alice")
    wm.append_turn(conv.id, "user", "my secret SSN 123-45-6789")
    wm.upsert_fact("user:alice:note", "card 4111111111111111")

    # The raw on-disk columns hold sealed tokens, not plaintext.
    raw_turn = sqlite3.connect(str(db)).execute("SELECT content FROM turns").fetchone()[0]
    raw_fact = sqlite3.connect(str(db)).execute("SELECT value FROM facts").fetchone()[0]
    assert raw_turn.startswith("MVKAR1:") and "123-45-6789" not in raw_turn
    assert raw_fact.startswith("MVKAR1:") and "4111111111111111" not in raw_fact

    # Reads transparently decrypt.
    assert wm.recent_turns(conv.id)[-1].content == "my secret SSN 123-45-6789"
    assert wm.get_facts()["user:alice:note"] == "card 4111111111111111"
    assert wm.get_fact("user:alice:note") == "card 4111111111111111"


def test_world_db_reads_legacy_plaintext(monkeypatch, tmp_path):
    from maverick.world_model import WorldModel

    db = tmp_path / "world.db"
    # Write WITHOUT encryption (legacy rows; the fixture left at_rest off).
    wm = WorldModel(db)
    conv = wm.get_or_create_conversation("slack", "bob")
    wm.append_turn(conv.id, "user", "plain legacy turn")
    wm.upsert_fact("user:bob:n", "plain legacy fact")

    # Now turn encryption on; existing plaintext rows still read back fine.
    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "1")
    wm2 = WorldModel(db)
    assert wm2.recent_turns(conv.id)[-1].content == "plain legacy turn"
    assert wm2.get_fact("user:bob:n") == "plain legacy fact"
