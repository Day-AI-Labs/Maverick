"""Tests for audit + world-model retention enforcement."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest


def _make_audit_file(audit_dir: Path, day: str, body: str = '{"v": 1}\n') -> Path:
    audit_dir.mkdir(parents=True, exist_ok=True)
    p = audit_dir / f"{day}.ndjson"
    p.write_text(body)
    return p


def test_purge_audit_files_disabled():
    from maverick.audit.retention import purge_audit_files
    res = purge_audit_files(days=0, audit_dir=Path("/nonexistent"))
    assert res["reason"] == "disabled"


def test_purge_audit_files_no_dir(tmp_path: Path):
    from maverick.audit.retention import purge_audit_files
    res = purge_audit_files(days=30, audit_dir=tmp_path / "nope")
    assert res["reason"] == "no audit dir"


def test_purge_audit_files_removes_old_keeps_recent(tmp_path: Path):
    from maverick.audit.retention import purge_audit_files
    audit_dir = tmp_path / "audit"
    _make_audit_file(audit_dir, "2025-01-01")
    _make_audit_file(audit_dir, "2025-06-15")
    _make_audit_file(audit_dir, "2025-06-25")
    _make_audit_file(audit_dir, "garbage")  # non-date file is preserved

    fixed_now = time.mktime(time.strptime("2025-06-30", "%Y-%m-%d"))
    res = purge_audit_files(days=10, audit_dir=audit_dir, now=fixed_now)
    removed = set(res["removed"])
    assert "2025-01-01.ndjson" in removed
    assert "2025-06-15.ndjson" in removed
    assert "2025-06-25.ndjson" not in removed
    # File still on disk:
    assert (audit_dir / "2025-06-25.ndjson").exists()
    assert (audit_dir / "garbage.ndjson").exists()
    assert not (audit_dir / "2025-01-01.ndjson").exists()


def test_purge_audit_files_dry_run(tmp_path: Path):
    from maverick.audit.retention import purge_audit_files
    audit_dir = tmp_path / "audit"
    _make_audit_file(audit_dir, "2024-01-01")
    fixed_now = time.mktime(time.strptime("2025-01-01", "%Y-%m-%d"))
    res = purge_audit_files(days=10, audit_dir=audit_dir, dry_run=True, now=fixed_now)
    assert "2024-01-01.ndjson" in res["removed"]
    # Dry run leaves file in place.
    assert (audit_dir / "2024-01-01.ndjson").exists()


def _seed_world_db(path: Path) -> None:
    """Create a minimal world.db with the columns retention.py touches."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE goals (id INTEGER PRIMARY KEY, status TEXT,
                            created_at REAL, updated_at REAL);
        CREATE TABLE episodes (id INTEGER PRIMARY KEY, goal_id INTEGER,
                               started_at REAL, ended_at REAL,
                               summary TEXT, outcome TEXT,
                               cost_dollars REAL, input_tokens INTEGER,
                               output_tokens INTEGER, tool_calls INTEGER);
        CREATE TABLE goal_events (id INTEGER PRIMARY KEY, goal_id INTEGER,
                                  agent TEXT, kind TEXT, content TEXT, ts REAL);
    """)
    conn.commit()
    conn.close()


def _insert_episode(db: Path, ended_at: float) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO episodes (started_at, ended_at, outcome) VALUES (?, ?, 'x')",
        (ended_at - 1, ended_at),
    )
    conn.commit()
    conn.close()


def _insert_event(db: Path, ts: float) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO goal_events (goal_id, agent, kind, content, ts) VALUES (1, 'a', 'k', '', ?)",
        (ts,),
    )
    conn.commit()
    conn.close()


def test_purge_world_episodes_removes_old(tmp_path: Path):
    from maverick.audit.retention import purge_world_episodes
    db = tmp_path / "world.db"
    _seed_world_db(db)
    now = 1_700_000_000.0
    _insert_episode(db, now - 100 * 86400)  # old
    _insert_episode(db, now - 10 * 86400)   # recent
    _insert_episode(db, now)                # fresh

    res = purge_world_episodes(days=30, db_path=db, now=now)
    assert res["deleted"] == 1

    conn = sqlite3.connect(str(db))
    (left,) = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()
    conn.close()
    assert left == 2


def test_purge_world_episodes_dry_run(tmp_path: Path):
    from maverick.audit.retention import purge_world_episodes
    db = tmp_path / "world.db"
    _seed_world_db(db)
    now = 1_700_000_000.0
    _insert_episode(db, now - 100 * 86400)

    res = purge_world_episodes(days=30, db_path=db, now=now, dry_run=True)
    assert res["deleted"] == 1
    conn = sqlite3.connect(str(db))
    (left,) = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()
    conn.close()
    assert left == 1  # still there


def test_purge_world_events_removes_old(tmp_path: Path):
    from maverick.audit.retention import purge_world_events
    db = tmp_path / "world.db"
    _seed_world_db(db)
    now = 1_700_000_000.0
    _insert_event(db, now - 200 * 86400)
    _insert_event(db, now - 5 * 86400)

    res = purge_world_events(days=30, db_path=db, now=now)
    assert res["deleted"] == 1


def test_enforce_no_config_returns_disabled():
    from maverick.audit.retention import enforce
    res = enforce(config={})
    assert res["status"] == "disabled"


def test_enforce_full_config(tmp_path: Path):
    from maverick.audit.retention import enforce
    audit_dir = tmp_path / "audit"
    db = tmp_path / "world.db"
    _seed_world_db(db)
    _make_audit_file(audit_dir, "2024-01-01")
    now = time.mktime(time.strptime("2025-06-30", "%Y-%m-%d"))
    _insert_episode(db, now - 200 * 86400)
    _insert_event(db, now - 365 * 86400)

    cfg = {"audit_days": 30, "episodes_days": 30, "events_days": 90}
    res = enforce(
        config=cfg, audit_dir=audit_dir, db_path=db, now=now,
    )
    assert res["audit"]["removed"] == ["2024-01-01.ndjson"]
    assert res["episodes"]["deleted"] == 1
    assert res["goal_events"]["deleted"] == 1


@pytest.mark.parametrize("days", [None, 0, -5])
def test_purge_helpers_disabled_with_bad_days(tmp_path: Path, days):
    from maverick.audit.retention import (
        purge_audit_files,
        purge_world_episodes,
        purge_world_events,
    )
    db = tmp_path / "world.db"
    _seed_world_db(db)
    assert purge_audit_files(days=days, audit_dir=tmp_path)["reason"] == "disabled"
    assert purge_world_episodes(days=days, db_path=db)["reason"] == "disabled"
    assert purge_world_events(days=days, db_path=db)["reason"] == "disabled"


def test_purge_missing_db_safe(tmp_path: Path):
    """No DB file -> no rows deleted, no exception."""
    from maverick.audit.retention import purge_world_episodes
    res = purge_world_episodes(days=30, db_path=tmp_path / "absent.db")
    assert res["deleted"] == 0
