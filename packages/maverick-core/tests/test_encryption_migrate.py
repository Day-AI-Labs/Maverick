"""maverick encryption migrate: seal pre-existing plaintext."""
from __future__ import annotations

import importlib.util
import sqlite3

import pytest
from maverick import crypto_at_rest as car

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
    monkeypatch.setattr(car, "_KEY_PATH", tmp_path / "keys" / "at_rest.key")


def test_migrate_requires_encryption_enabled(tmp_path):
    from maverick.crypto_at_rest import EncryptionUnavailable
    from maverick.encryption_migrate import migrate_world_db

    with pytest.raises(EncryptionUnavailable):
        migrate_world_db(tmp_path / "world.db")  # at_rest off -> refuse, never plaintext


@requires_crypto
def test_migrate_seals_existing_plaintext(monkeypatch, tmp_path):
    from maverick.encryption_migrate import migrate_world_db
    from maverick.world_model import WorldModel

    db = tmp_path / "world.db"
    # Write everything as plaintext (encryption off).
    wm = WorldModel(db)
    conv = wm.get_or_create_conversation("slack", "u")
    wm.append_turn(conv.id, "user", "turn SSN 123-45-6789")
    wm.upsert_fact("k", "fact 4111111111111111")
    gid = wm.create_goal("g", "d")
    wm.append_message(gid, "user", "message secret")
    qid = wm.ask("question secret", goal_id=gid)
    wm.answer(qid, "answer secret")

    # Enable encryption and seal the existing rows.
    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "1")
    assert migrate_world_db(db) == {
        "turns.content": 1, "facts.value": 1, "messages.content": 1,
        "questions.question": 1, "questions.answer": 1,
        "goals.title": 1, "goals.description": 1, "goals.result": 0,
        "goal_events.content": 0,
        "episodes.summary": 0, "episodes.outcome": 0,
        "approvals.action": 0, "approvals.scope": 0, "approvals.detail": 0,
    }

    # On disk the columns are now sealed (ciphertext, no plaintext).
    c = sqlite3.connect(str(db))
    turn = c.execute("SELECT content FROM turns").fetchone()[0]
    assert turn.startswith("MVKAR1:") and "123-45-6789" not in turn
    assert c.execute("SELECT value FROM facts").fetchone()[0].startswith("MVKAR1:")
    assert c.execute("SELECT title FROM goals").fetchone()[0].startswith("MVKAR1:")

    # Reads still return plaintext.
    wm2 = WorldModel(db)
    assert wm2.recent_turns(conv.id)[-1].content == "turn SSN 123-45-6789"
    assert wm2.get_fact("k") == "fact 4111111111111111"
    assert wm2.get_goal(gid).title == "g"          # goal content round-trips

    # Idempotent: a second run seals nothing.
    assert migrate_world_db(db) == {
        "turns.content": 0, "facts.value": 0, "messages.content": 0,
        "questions.question": 0, "questions.answer": 0,
        "goals.title": 0, "goals.description": 0, "goals.result": 0,
        "goal_events.content": 0,
        "episodes.summary": 0, "episodes.outcome": 0,
        "approvals.action": 0, "approvals.scope": 0, "approvals.detail": 0,
    }


@requires_crypto
def test_migrate_dry_run_writes_nothing(monkeypatch, tmp_path):
    from maverick.encryption_migrate import migrate_world_db
    from maverick.world_model import WorldModel

    db = tmp_path / "world.db"
    wm = WorldModel(db)
    conv = wm.get_or_create_conversation("slack", "u")
    wm.append_turn(conv.id, "user", "still plaintext")

    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "1")
    assert migrate_world_db(db, dry_run=True)["turns.content"] == 1
    # Unchanged on disk.
    raw = sqlite3.connect(str(db)).execute("SELECT content FROM turns").fetchone()[0]
    assert raw == "still plaintext"


def _all_db_bytes(db):
    """The DB main file + its WAL/SHM sidecars, concatenated."""
    blob = db.read_bytes() if db.exists() else b""
    for suf in ("-wal", "-shm"):
        p = db.with_name(db.name + suf)
        if p.exists():
            blob += p.read_bytes()
    return blob


@requires_crypto
def test_migrate_leaves_no_plaintext_residue_in_the_db_file(monkeypatch, tmp_path):
    from maverick.encryption_migrate import migrate_world_db
    from maverick.world_model import WorldModel

    db = tmp_path / "world.db"
    wm = WorldModel(db)
    marker = "RESIDUE-MARKER-4111111111111111"
    wm.create_goal(marker, "desc")
    wm.conn.close()                                   # release the DB (offline migrate)
    assert marker.encode() in _all_db_bytes(db)       # plaintext present before

    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "1")
    migrate_world_db(db)

    # secure_delete zeroed the freed cells + VACUUM/checkpoint rebuilt the file:
    # the pre-encryption plaintext is gone from the DB file and the WAL sidecar.
    assert marker.encode() not in _all_db_bytes(db)
