"""World-model search must backfill the messages_fts index on upgrade.

The FTS5 external-content table indexes only FUTURE writes (via triggers), so a
database whose messages predate the index -- created before messages_fts
shipped -- carried unindexed history that search_messages() silently missed.
The v10 migration runs a one-time `rebuild` so that history becomes searchable.
"""
from __future__ import annotations

from pathlib import Path

from maverick.world_model import SCHEMA_VERSION, WorldModel


def test_fts_index_is_rebuilt_on_upgrade(tmp_path: Path) -> None:
    db = tmp_path / "w.db"
    w = WorldModel(db)
    gid = w.create_goal("g", "")
    w.append_message(gid, "user", "pineapples are spiky tropical fruit")
    assert len(w.search_messages("pineapples")) == 1

    # Simulate a DB whose messages predate the FTS index: clear the index and
    # roll the stored schema version back so the next open re-migrates.
    w.conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('delete-all')")
    w.conn.execute("UPDATE schema_version SET version = 9")
    w.conn.commit()
    assert len(w.search_messages("pineapples")) == 0  # the bug: unindexed history
    w.conn.close()

    # Reopening runs MIGRATIONS[10] -> rebuild -> the history is searchable again.
    w2 = WorldModel(db)
    assert w2.schema_version == SCHEMA_VERSION
    assert len(w2.search_messages("pineapples")) == 1
