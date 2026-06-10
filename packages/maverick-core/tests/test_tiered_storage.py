"""Tests for tiered world-model storage (hot SQLite + cold archive files).

Deterministic and offline: a real WorldModel on tmp_path, rows backdated via
raw UPDATEs (record_episode/append_event always stamp time.time()), and the
cold format pinned to the stdlib jsonl fallback unless a test stubs pyarrow
itself.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest
from maverick import tiered_storage as ts
from maverick.world_model import open_world

DAY = 86_400.0
_HAS_PYARROW = importlib.util.find_spec("pyarrow") is not None


@pytest.fixture
def world(tmp_path):
    w = open_world(tmp_path / "w.db")
    yield w
    w.close()


@pytest.fixture
def force_jsonl(monkeypatch):
    """Pin the cold format to jsonl so results don't depend on the host
    having pyarrow installed (the brief's `sys.modules pyarrow=None` trick:
    a None entry makes `import pyarrow` raise)."""
    monkeypatch.setitem(sys.modules, "pyarrow", None)


def _backdate_episode(world, episode_id: int, epoch: float) -> None:
    world.conn.execute(
        "UPDATE episodes SET started_at = ? WHERE id = ?", (epoch, episode_id))
    world.conn.commit()


def _backdate_event(world, event_id: int, epoch: float) -> None:
    world.conn.execute(
        "UPDATE goal_events SET ts = ? WHERE id = ?", (epoch, event_id))
    world.conn.commit()


def _count(world, table: str) -> int:
    return world.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _seed(world) -> dict:
    """One goal; one old + one new episode; one old + one new event."""
    gid = world.create_goal("long-running goal")
    old_ep = world.start_episode(gid)
    world.end_episode(old_ep, "old-summary", "ok")
    _backdate_episode(world, old_ep, time.time() - 90 * DAY)
    new_ep = world.start_episode(gid)
    old_ev = world.append_event(gid, "orchestrator", "note", "old event content")
    _backdate_event(world, old_ev, time.time() - 90 * DAY)
    new_ev = world.append_event(gid, "orchestrator", "note", "new event content")
    return {"gid": gid, "old_ep": old_ep, "new_ep": new_ep,
            "old_ev": old_ev, "new_ev": new_ev}


# ---- cutoff_epoch -------------------------------------------------------------

def test_cutoff_epoch_is_pure_and_injectable():
    assert ts.cutoff_epoch(30, now=1000 * DAY) == 970 * DAY
    assert ts.cutoff_epoch(0.5, now=10 * DAY) == 9.5 * DAY
    assert ts.cutoff_epoch(0, now=123.0) == 123.0


def test_cutoff_epoch_rejects_negative_days():
    with pytest.raises(ValueError):
        ts.cutoff_epoch(-1, now=0.0)


# ---- archive ------------------------------------------------------------------

def test_archive_moves_old_rows_and_keeps_new(world, tmp_path, force_jsonl):
    ids = _seed(world)
    cold = tmp_path / "cold"

    result = ts.archive(world, older_than_days=30, cold_dir=cold)

    assert result.rows_archived == {"episodes": 1, "goal_events": 1}
    assert len(result.files) == 2
    assert all(f.name.endswith(".jsonl.gz") for f in result.files)

    # Old rows are gone from SQLite; new rows are untouched.
    remaining_eps = [r["id"] for r in world.conn.execute("SELECT id FROM episodes")]
    remaining_evs = [r["id"] for r in world.conn.execute("SELECT id FROM goal_events")]
    assert remaining_eps == [ids["new_ep"]]
    assert remaining_evs == [ids["new_ev"]]

    # Archived rows are present and readable in the cold store.
    cold_eps = list(ts.read_cold(cold, "episodes"))
    cold_evs = list(ts.read_cold(cold, "goal_events"))
    assert [r["id"] for r in cold_eps] == [ids["old_ep"]]
    assert cold_eps[0]["summary"] == "old-summary"
    assert [r["id"] for r in cold_evs] == [ids["old_ev"]]
    assert cold_evs[0]["content"] == "old event content"


def test_archive_with_nothing_old_writes_no_files(world, tmp_path, force_jsonl):
    gid = world.create_goal("fresh goal")
    world.start_episode(gid)
    world.append_event(gid, "a", "note", "fresh")

    result = ts.archive(world, older_than_days=30, cold_dir=tmp_path / "cold")

    assert result.rows_archived == {"episodes": 0, "goal_events": 0}
    assert result.files == []
    assert _count(world, "episodes") == 1 and _count(world, "goal_events") == 1


def test_cold_file_named_after_min_max_row_dates(world, tmp_path, force_jsonl):
    gid = world.create_goal("g")
    e1 = world.append_event(gid, "a", "k", "first")
    e2 = world.append_event(gid, "a", "k", "second")
    _backdate_event(world, e1, datetime(2025, 1, 10, 12, tzinfo=timezone.utc).timestamp())
    _backdate_event(world, e2, datetime(2025, 1, 20, 12, tzinfo=timezone.utc).timestamp())

    result = ts.archive(world, older_than_days=30, cold_dir=tmp_path / "cold",
                        tables=("goal_events",))

    assert [f.name for f in result.files] == ["goal_events-20250110-20250120.jsonl.gz"]


def test_same_date_range_rerun_gets_dedup_suffix(world, tmp_path, force_jsonl):
    stamp = datetime(2025, 3, 1, 12, tzinfo=timezone.utc).timestamp()
    gid = world.create_goal("g")
    cold = tmp_path / "cold"
    for expected in ("goal_events-20250301-20250301.jsonl.gz",
                     "goal_events-20250301-20250301-2.jsonl.gz"):
        ev = world.append_event(gid, "a", "k", "x")
        _backdate_event(world, ev, stamp)
        result = ts.archive(world, older_than_days=30, cold_dir=cold,
                            tables=("goal_events",))
        assert [f.name for f in result.files] == [expected]
    assert len(list(ts.read_cold(cold, "goal_events"))) == 2


def test_file_write_failure_leaves_sqlite_intact(world, tmp_path, monkeypatch):
    _seed(world)
    eps_before, evs_before = _count(world, "episodes"), _count(world, "goal_events")

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(ts, "_write_cold_file", _boom)
    with pytest.raises(OSError):
        ts.archive(world, older_than_days=30, cold_dir=tmp_path / "cold")

    assert _count(world, "episodes") == eps_before
    assert _count(world, "goal_events") == evs_before
    assert list((tmp_path / "cold").glob("*")) == []


def test_jsonl_fallback_when_pyarrow_unimportable(world, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyarrow", None)  # import pyarrow now raises
    _seed(world)

    result = ts.archive(world, older_than_days=30, cold_dir=tmp_path / "cold")

    assert all(f.name.endswith(".jsonl.gz") for f in result.files)
    # The fallback file is plain gzip JSONL: readable without any third party.
    with gzip.open(result.files[0], "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    assert rows and "id" in rows[0]


def test_parquet_preferred_when_pyarrow_importable(world, tmp_path, monkeypatch):
    """Stub pyarrow so the parquet branch (write + read_cold) is exercised
    without the real dependency installed."""
    store: dict[str, list[dict]] = {}

    fake_pa = types.ModuleType("pyarrow")
    fake_pq = types.ModuleType("pyarrow.parquet")
    fake_pa.Table = types.SimpleNamespace(from_pylist=lambda rows: rows)

    def _write_table(rows, path):
        Path(path).write_text(json.dumps(rows))
        store["written"] = rows

    def _read_table(path):
        rows = json.loads(Path(path).read_text())
        return types.SimpleNamespace(to_pylist=lambda: rows)

    fake_pq.write_table = _write_table
    fake_pq.read_table = _read_table
    fake_pa.parquet = fake_pq
    monkeypatch.setitem(sys.modules, "pyarrow", fake_pa)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", fake_pq)

    ids = _seed(world)
    cold = tmp_path / "cold"
    result = ts.archive(world, older_than_days=30, cold_dir=cold)

    assert all(f.name.endswith(".parquet") for f in result.files)
    assert store["written"]  # rows went through the parquet writer
    assert _count(world, "episodes") == 1  # old row deleted after the write
    cold_ids = {r["id"] for r in ts.read_cold(cold, "episodes")}
    assert cold_ids == {ids["old_ep"]}


@pytest.mark.skipif(not _HAS_PYARROW, reason="pyarrow not installed")
def test_real_parquet_roundtrip(world, tmp_path):
    ids = _seed(world)
    cold = tmp_path / "cold"
    result = ts.archive(world, older_than_days=30, cold_dir=cold)
    assert all(f.name.endswith(".parquet") for f in result.files)
    cold_eps = list(ts.read_cold(cold, "episodes"))
    assert [r["id"] for r in cold_eps] == [ids["old_ep"]]
    assert cold_eps[0]["summary"] == "old-summary"


def test_episode_referenced_by_a_fact_is_pinned_hot(world, tmp_path, force_jsonl):
    ids = _seed(world)
    # foreign_keys=ON: deleting this episode would violate facts.source_episode_id.
    world.upsert_fact("learned.thing", "value", episode_id=ids["old_ep"])

    result = ts.archive(world, older_than_days=30, cold_dir=tmp_path / "cold")

    assert result.rows_archived == {"episodes": 0, "goal_events": 1}
    eps = [r["id"] for r in world.conn.execute("SELECT id FROM episodes")]
    assert ids["old_ep"] in eps  # pinned, still hot


def test_unknown_table_rejected(world, tmp_path):
    with pytest.raises(ValueError, match="unknown table"):
        ts.archive(world, older_than_days=30, cold_dir=tmp_path / "cold",
                   tables=("episodes", "facts"))


def test_non_sqlite_world_rejected(tmp_path):
    with pytest.raises(TypeError):
        ts.archive(object(), older_than_days=30, cold_dir=tmp_path / "cold")


# ---- read_cold ----------------------------------------------------------------

def test_read_cold_on_missing_or_empty_dir_yields_nothing(tmp_path):
    assert list(ts.read_cold(tmp_path / "nope", "episodes")) == []
    (tmp_path / "empty").mkdir()
    assert list(ts.read_cold(tmp_path / "empty", "episodes")) == []


def test_read_cold_ignores_foreign_and_partial_files(tmp_path, world, force_jsonl):
    _seed(world)
    cold = tmp_path / "cold"
    ts.archive(world, older_than_days=30, cold_dir=cold)
    (cold / "episodes-20990101-20990101.jsonl.gz.tmp").write_text("garbage")
    rows = list(ts.read_cold(cold, "episodes"))
    assert len(rows) == 1  # the .tmp leftover is skipped, not parsed


# ---- configured_archive -------------------------------------------------------

@pytest.fixture
def _clean_knobs(monkeypatch):
    monkeypatch.delenv("MAVERICK_WORLD_COLD_DIR", raising=False)
    monkeypatch.delenv("MAVERICK_WORLD_ARCHIVE_AFTER_DAYS", raising=False)
    monkeypatch.delenv("MAVERICK_CONFIG", raising=False)


def test_configured_archive_is_noop_when_unset(world, _clean_knobs):
    assert ts.configured_archive(world) is None


def test_configured_archive_via_env(world, tmp_path, monkeypatch, _clean_knobs, force_jsonl):
    _seed(world)
    monkeypatch.setenv("MAVERICK_WORLD_COLD_DIR", str(tmp_path / "cold"))
    monkeypatch.setenv("MAVERICK_WORLD_ARCHIVE_AFTER_DAYS", "30")

    result = ts.configured_archive(world)

    assert result is not None
    assert result.rows_archived == {"episodes": 1, "goal_events": 1}


def test_configured_archive_via_config_file(world, tmp_path, _clean_knobs, force_jsonl):
    # conftest pins HOME to tmp_path, so this is the config load_config() reads.
    _seed(world)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cold = tmp_path / "cold-from-config"
    (cfg_dir / "config.toml").write_text(
        f'[world_model]\ncold_dir = "{cold}"\narchive_after_days = 30\n'
    )

    result = ts.configured_archive(world)

    assert result is not None and result.rows_archived["goal_events"] == 1
    assert list(ts.read_cold(cold, "goal_events"))


def test_configured_archive_rejects_bad_days(world, tmp_path, monkeypatch, _clean_knobs):
    monkeypatch.setenv("MAVERICK_WORLD_COLD_DIR", str(tmp_path / "cold"))
    for bad in ("banana", "0", "-3"):
        monkeypatch.setenv("MAVERICK_WORLD_ARCHIVE_AFTER_DAYS", bad)
        assert ts.configured_archive(world) is None
