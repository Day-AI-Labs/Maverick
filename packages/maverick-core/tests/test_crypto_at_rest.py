"""Encryption at rest: AES-256-GCM seal/unseal + key management."""
from __future__ import annotations

import base64
import importlib.util

import pytest
from maverick import crypto_at_rest as car

# AES-GCM needs the optional 'cryptography' extra; skip only the tests that
# exercise encryption where it is absent, matching the audit-signing tests
# (test_audit_anchor.py). Key-management tests still run without the extra.
requires_crypto = pytest.mark.skipif(
    importlib.util.find_spec("cryptography") is None,
    reason="cryptography extra is not installed",
)


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


@requires_crypto
def test_seal_unseal_roundtrip():
    secret = b"patient SSN 123-45-6789"
    blob = car.seal(secret)
    assert car.is_sealed(blob)
    assert blob != secret  # actually encrypted
    assert b"123-45-6789" not in blob  # plaintext not present in ciphertext
    assert car.unseal(blob) == secret


@requires_crypto
def test_text_helpers():
    blob = car.seal_text("hello — é")
    assert car.unseal_to_text(blob) == "hello — é"


def test_unseal_passthrough_for_plaintext():
    # A blob without the magic header is legacy plaintext -> returned as-is.
    assert car.unseal(b"plain old note") == b"plain old note"
    assert car.is_sealed(b"plain old note") is False


@requires_crypto
def test_each_seal_uses_fresh_nonce():
    a, b = car.seal(b"same"), car.seal(b"same")
    assert a != b  # nonce randomization -> distinct ciphertexts
    assert car.unseal(a) == car.unseal(b) == b"same"


@requires_crypto
def test_tamper_is_detected():
    blob = bytearray(car.seal(b"important"))
    blob[-1] ^= 0x01  # flip a tag bit
    with pytest.raises(Exception):  # noqa: B017 - InvalidTag from the AEAD
        car.unseal(bytes(blob))


@requires_crypto
def test_injected_key_hex_and_base64(monkeypatch):
    key = bytes(range(32))
    monkeypatch.setenv("MAVERICK_ENCRYPTION_KEY", key.hex())
    blob = car.seal(b"x")
    monkeypatch.setenv("MAVERICK_ENCRYPTION_KEY", base64.b64encode(key).decode())
    assert car.unseal(blob) == b"x"  # same key, different encoding -> opens


@requires_crypto
def test_injected_key_wrong_size_fails(monkeypatch):
    monkeypatch.setenv("MAVERICK_ENCRYPTION_KEY", "00" * 16)  # 16 bytes, not 32
    with pytest.raises(car.EncryptionUnavailable):
        car.seal(b"x")


@requires_crypto
def test_generated_key_persists_and_chmod(monkeypatch):
    blob = car.seal(b"persist me")
    assert car._KEY_PATH.exists()
    assert (car._KEY_PATH.stat().st_mode & 0o777) == 0o600
    assert (car._KEY_PATH.parent.stat().st_mode & 0o777) == 0o700
    # A second seal reuses the same on-disk key, so unseal still works.
    assert car.unseal(blob) == b"persist me"


def test_generated_key_is_created_private_atomically(monkeypatch):
    original_open = car.os.open
    observed = {}

    def checked_open(path, flags, mode=0o777, *args, **kwargs):
        observed["exclusive_create"] = bool(flags & car.os.O_EXCL)
        observed["requested_mode"] = mode
        observed["parent_mode_before_create"] = (
            car._KEY_PATH.parent.stat().st_mode & 0o777
        )
        return original_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(car.os, "open", checked_open)

    car._load_or_create_key()

    assert observed == {
        "exclusive_create": True,
        "requested_mode": 0o600,
        "parent_mode_before_create": 0o700,
    }
    assert (car._KEY_PATH.stat().st_mode & 0o777) == 0o600


def test_existing_key_permissions_are_repaired_before_read(monkeypatch):
    car._KEY_PATH.parent.mkdir(parents=True)
    car._KEY_PATH.parent.chmod(0o755)
    car._KEY_PATH.write_text((b"k" * 32).hex(), encoding="utf-8")
    car._KEY_PATH.chmod(0o644)
    path_type = type(car._KEY_PATH)
    original_read_text = path_type.read_text
    observed = {}

    def checked_read_text(self, *args, **kwargs):
        if self == car._KEY_PATH:
            observed["key_mode_before_read"] = self.stat().st_mode & 0o777
            observed["parent_mode_before_read"] = self.parent.stat().st_mode & 0o777
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(path_type, "read_text", checked_read_text)

    assert car._load_or_create_key() == b"k" * 32
    assert observed == {
        "key_mode_before_read": 0o600,
        "parent_mode_before_read": 0o700,
    }


@requires_crypto
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


@requires_crypto
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


@requires_crypto
def test_world_db_seals_messages(monkeypatch, tmp_path):
    import sqlite3

    from maverick.world_model import WorldModel

    db = tmp_path / "world.db"
    wm = WorldModel(db)
    gid = wm.create_goal("g", "d")

    # A legacy plaintext message (encryption off) is searchable via FTS.
    wm.append_message(gid, "user", "findable plaintext token")
    assert any("findable" in m["content"] for m in wm.search_messages("findable"))

    # With encryption on, new message content is sealed on disk.
    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "1")
    wm.append_message(gid, "assistant", "secret SSN 123-45-6789")
    raw = sqlite3.connect(str(db)).execute(
        "SELECT content FROM messages WHERE role = 'assistant'"
    ).fetchone()[0]
    assert raw.startswith("MVKAR1:") and "123-45-6789" not in raw

    # Search can't match ciphertext, so the encrypted message is not returned;
    # the legacy plaintext message still is, and comes back decrypted.
    hits = {m["content"] for m in wm.search_messages("findable")}
    assert "findable plaintext token" in hits
    assert all("123-45-6789" not in c for c in hits)


@requires_crypto
def test_world_db_seals_questions(monkeypatch, tmp_path):
    import sqlite3

    from maverick.world_model import WorldModel

    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "1")
    db = tmp_path / "world.db"
    wm = WorldModel(db)
    gid = wm.create_goal("g", "d")
    qid = wm.ask("secret question SSN 123-45-6789?", goal_id=gid)

    # The read path used by CLI / dashboard / MCP decrypts transparently.
    assert any("123-45-6789" in q.question for q in wm.open_questions(gid))

    wm.answer(qid, "secret answer 987-65-4321")

    # Raw on-disk columns are sealed.
    row = sqlite3.connect(str(db)).execute(
        "SELECT question, answer FROM questions"
    ).fetchone()
    assert row[0].startswith("MVKAR1:") and "123-45-6789" not in row[0]
    assert row[1].startswith("MVKAR1:") and "987-65-4321" not in row[1]

    # all_questions decrypts both fields.
    q = wm.all_questions(gid)[0]
    assert q.question == "secret question SSN 123-45-6789?"
    assert q.answer == "secret answer 987-65-4321"
