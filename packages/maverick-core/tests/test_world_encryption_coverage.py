"""At-rest encryption coverage for goal content + goal events, and the strict
read-side guard that closes the plaintext-passthrough hole."""
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
    for v in ("MAVERICK_ENCRYPT_AT_REST", "MAVERICK_ENCRYPTION_KEY",
              "MAVERICK_ENTERPRISE", "MAVERICK_ENCRYPT_STRICT"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})
    monkeypatch.setattr(car, "_KEY_PATH", tmp_path / "keys" / "at_rest.key")


@requires_crypto
def test_goal_content_sealed_on_disk_and_round_trips(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "1")
    from maverick.world_model import WorldModel
    db = tmp_path / "world.db"
    wm = WorldModel(db)
    gid = wm.create_goal("exfil the SSN 123-45-6789", "sensitive description")
    wm.set_goal_status(gid, "done", result="the secret result")
    wm.append_event(gid, "agent-1", "note", "event payload secret")

    # On disk: sealed, no plaintext leaks.
    c = sqlite3.connect(str(db))
    title, desc, result = c.execute(
        "SELECT title, description, result FROM goals WHERE id=?", (gid,)
    ).fetchone()
    assert title.startswith("MVKAR1:") and "123-45-6789" not in title
    assert desc.startswith("MVKAR1:") and result.startswith("MVKAR1:")
    ev = c.execute(
        "SELECT content FROM goal_events WHERE goal_id=?", (gid,)
    ).fetchone()[0]
    assert ev.startswith("MVKAR1:") and "secret" not in ev

    # Reads round-trip to plaintext through every accessor.
    g = wm.get_goal(gid)
    assert g.title == "exfil the SSN 123-45-6789"
    assert g.description == "sensitive description"
    assert g.result == "the secret result"
    assert [x for x in wm.list_goals() if x.id == gid][0].title == g.title
    assert wm.goal_events(gid)[0].content == "event payload secret"


@requires_crypto
def test_goal_content_plaintext_when_encryption_off(tmp_path):
    from maverick.world_model import WorldModel
    db = tmp_path / "world.db"
    wm = WorldModel(db)
    gid = wm.create_goal("plain title", "plain desc")
    raw = sqlite3.connect(str(db)).execute(
        "SELECT title FROM goals WHERE id=?", (gid,)
    ).fetchone()[0]
    assert raw == "plain title"                    # off -> stored unchanged
    assert wm.get_goal(gid).title == "plain title"


@requires_crypto
def test_strict_mode_withholds_unsealed_value_in_a_sealed_column(monkeypatch, tmp_path):
    # Plaintext in a sealed column (tampering, or un-migrated legacy) must not be
    # served as trusted plaintext once strict is on.
    from maverick.world_model import _UNSEALED_WITHHELD, WorldModel
    db = tmp_path / "world.db"
    wm = WorldModel(db)
    gid = wm.create_goal("unsealed injected title", "d")   # written plaintext

    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "1")
    monkeypatch.setenv("MAVERICK_ENCRYPT_STRICT", "1")
    assert wm.get_goal(gid).title == _UNSEALED_WITHHELD


@requires_crypto
def test_non_strict_passes_through_legacy_plaintext(monkeypatch, tmp_path):
    from maverick.world_model import WorldModel
    db = tmp_path / "world.db"
    wm = WorldModel(db)
    gid = wm.create_goal("legacy title", "d")      # plaintext, pre-migration

    monkeypatch.setenv("MAVERICK_ENCRYPT_AT_REST", "1")   # strict OFF (default)
    assert wm.get_goal(gid).title == "legacy title"        # still readable
