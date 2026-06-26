"""Tiered world-model storage: hot SQLite + cold archive files (roadmap: 2027 H1 performance).

The world model (``world_model.py``) accumulates ``episodes`` and
``goal_events`` rows forever. Both tables are append-mostly and only the
recent window is read on the hot path (dashboard, recall, monitor), yet every
row stays in SQLite -- the file grows without bound and the hot queries page
through ever-colder index ranges. This module moves rows older than a cutoff
into **cold files** on disk and deletes them from SQLite, keeping the hot
store small while history stays queryable via :func:`read_cold`.

Cold format: **parquet** (via ``pyarrow``, shipped by the ``[pandas]`` extra)
is preferred -- columnar, compressed, readable by any analytics stack. When
pyarrow isn't importable the writer falls back to **gzip JSONL**, which needs
only the stdlib, so archival always works. :func:`read_cold` reads both, so a
mixed directory (one host wrote jsonl, another parquet) is fine. Files are
named ``<table>-<YYYYMMDD>-<YYYYMMDD>.parquet|.jsonl.gz`` after the UTC date
range of the rows inside (a ``-N`` suffix dedupes a same-range rerun).

Safety order, per table: SELECT the expired rows, write the cold file, THEN
delete -- one transaction per table. If the file write fails, nothing is
deleted (the partial file is removed and the error propagates); a row is
never dropped from SQLite unless its bytes are durably in the cold store
first. Tables commit independently, so a failure on the second table leaves
the first one's completed archive intact. Column values are copied verbatim,
so fields sealed by at-rest encryption stay sealed in the cold file.
Episodes still referenced by ``facts.source_episode_id`` are pinned hot
(the world model runs with ``foreign_keys=ON``; deleting them would raise).

This module never runs on its own. The operator (or a cron job) calls
:func:`archive` directly, or :func:`configured_archive`, which is a no-op
returning ``None`` until both knobs are set::

    [world_model]
    cold_dir = "~/.maverick/cold"
    archive_after_days = 90

Env overrides: ``MAVERICK_WORLD_COLD_DIR`` / ``MAVERICK_WORLD_ARCHIVE_AFTER_DAYS``.
"""
from __future__ import annotations

import gzip
import importlib
import io
import json
import logging
import os
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Archivable tables -> their row-timestamp column. Both are REAL epoch
# seconds written by time.time() in world_model.py: episodes stamps
# ``started_at`` (NOT NULL; ``ended_at`` is NULL while in flight) and
# goal_events stamps ``ts``.
_TS_COLUMNS = {"episodes": "started_at", "goal_events": "ts"}

# Rows that live tables still reference must stay hot: facts.source_episode_id
# REFERENCES episodes(id) and the connection runs with foreign_keys=ON, so
# deleting a referenced episode would raise IntegrityError mid-archive.
_PIN_FILTERS = {
    "episodes": (
        " AND id NOT IN (SELECT source_episode_id FROM facts"
        " WHERE source_episode_id IS NOT NULL)"
    ),
}

_DAY_SECONDS = 86_400.0
_DELETE_CHUNK = 500  # stay well under SQLite's host-parameter limit


def cutoff_epoch(older_than_days: float, now: float | None = None) -> float:
    """Epoch-seconds cutoff: rows stamped strictly below it are cold.

    Pure -- ``now`` is injectable so tests pin it. ``older_than_days`` may be
    fractional; a negative value is a caller bug and raises.
    """
    if older_than_days < 0:
        raise ValueError("older_than_days must be >= 0")
    base = time.time() if now is None else float(now)
    return base - float(older_than_days) * _DAY_SECONDS


@dataclass(frozen=True)
class ArchiveResult:
    rows_archived: dict[str, int]  # table -> rows moved to cold
    files: list[Path]              # cold files written (one per non-empty table)


def _have_pyarrow() -> bool:
    try:
        importlib.import_module("pyarrow.parquet")
        return True
    except Exception:
        return False


def _have_zstd() -> bool:
    try:
        importlib.import_module("zstandard")
        return True
    except Exception:
        return False


def _cold_codec() -> str:
    """Cold-archive codec: ``auto`` (default) | ``zstd`` | ``gzip`` | ``parquet``.

    ``auto`` reproduces the historical choice (parquet when pyarrow is present,
    else gzip JSONL) so an un-set deployment is byte-for-byte unchanged. ``zstd``
    writes ``.jsonl.zst`` (smaller + faster than gzip) when ``zstandard`` is
    importable, gracefully falling back to gzip otherwise. Read from
    ``[world_model] cold_codec`` (env ``MAVERICK_WORLD_COLD_CODEC`` wins).
    """
    val = os.environ.get("MAVERICK_WORLD_COLD_CODEC", "").strip().lower()
    if not val:
        val = str(_world_cfg().get("cold_codec", "auto")).strip().lower()
    return val if val in ("auto", "zstd", "gzip", "parquet") else "auto"


def _choose_format(codec: str):
    """Return ``(ext, writer)`` for the codec, with graceful fallbacks."""
    if codec in ("auto", "parquet") and _have_pyarrow():
        return ".parquet", _write_parquet
    if codec == "zstd" and _have_zstd():
        return ".jsonl.zst", _write_jsonl_zst
    return ".jsonl.gz", _write_jsonl_gz


def _yyyymmdd(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y%m%d")


def _publish_unique(cold_dir: Path, stem: str, ext: str, src: Path) -> Path:
    """Atomically publish the fully-written ``src`` under a never-clobber name.

    A plain ``while path.exists()`` then ``os.replace`` is a TOCTOU: two
    processes archiving the same date-range both see the same ``-N`` free and
    both replace onto it, so one silently clobbers the other's cold file -- and
    the SQLite rows were already deleted on the assumption the cold file is
    durable, so that is permanent data loss. Instead ``os.link`` ``src`` onto
    each candidate name in turn: ``link`` is atomic and fails with
    ``FileExistsError`` if the name is already taken, so the winner owns the
    name and the loser just tries the next ``-N``. Because ``src`` is already
    complete, the published file is never observed half-written or empty (unlike
    an O_EXCL placeholder, which ``read_cold`` would pick up and fail to parse).
    Falls back to the historical exists()+replace on a platform without
    hard-links.
    """
    n = 1
    while True:
        path = cold_dir / (f"{stem}{ext}" if n == 1 else f"{stem}-{n}{ext}")
        try:
            os.link(str(src), str(path))
            return path
        except FileExistsError:
            n += 1
            continue
        except OSError:
            # No hard-link support (exotic FS / platform): degrade to the old
            # best-effort scheme. Still better than nothing; the link path is
            # the one that closes the race on POSIX.
            while path.exists():
                n += 1
                path = cold_dir / f"{stem}-{n}{ext}"
            os.replace(str(src), str(path))
            return path


def _write_parquet(rows: list[dict], path: Path) -> None:
    pa = importlib.import_module("pyarrow")
    papq = importlib.import_module("pyarrow.parquet")
    papq.write_table(pa.Table.from_pylist(rows), str(path))


def _write_jsonl_gz(rows: list[dict], path: Path) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")


def _write_jsonl_zst(rows: list[dict], path: Path) -> None:
    zstd = importlib.import_module("zstandard")
    cctx = zstd.ZstdCompressor(level=10)
    with open(path, "wb") as raw, cctx.stream_writer(raw) as comp:
        for row in rows:
            comp.write((json.dumps(row, default=str) + "\n").encode("utf-8"))


def _write_cold_file(cold_dir: Path, table: str, ts_col: str, rows: list[dict]) -> Path:
    """Write ``rows`` to a new cold file; return its path.

    Format per the configured codec (``auto`` = parquet when pyarrow imports,
    gzip JSONL otherwise; ``zstd`` = ``.jsonl.zst``). Written to a temp name
    then atomically renamed, so a crash mid-write never leaves a half-file that
    :func:`read_cold` would pick up. Raises on any failure -- the caller deletes
    nothing from SQLite in that case.
    """
    lo = _yyyymmdd(min(r[ts_col] for r in rows))
    hi = _yyyymmdd(max(r[ts_col] for r in rows))
    ext, writer = _choose_format(_cold_codec())
    cold_dir.mkdir(parents=True, exist_ok=True)
    # Write the whole file to a UNIQUE temp first (read_cold skips ".tmp"), then
    # atomically publish it under a never-clobber name. A fixed ".tmp" derived
    # from the final name would also collide between two same-range archivers.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(cold_dir), prefix=f".{table}-", suffix=ext + ".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        writer(rows, tmp)
        try:
            os.chmod(tmp, 0o600)  # same posture as world.db: content may be sensitive
        except OSError:
            pass
        path = _publish_unique(cold_dir, f"{table}-{lo}-{hi}", ext, tmp)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    # On the hard-link path the published file is a second link to tmp; drop the
    # temp name so only the final cold file remains. (On the os.replace fallback
    # tmp was already renamed away, so this unlink is a no-op miss.)
    try:
        tmp.unlink()
    except OSError:
        pass
    return path


def archive(
    world,
    *,
    older_than_days: float,
    cold_dir: str | Path,
    tables: tuple[str, ...] = ("episodes", "goal_events"),
) -> ArchiveResult:
    """Move rows older than the cutoff from SQLite into cold files.

    ``world`` must be the SQLite ``WorldModel`` (cold tiering is not
    implemented for the Postgres backend). Per table, runs under the world
    model's write lock in a single transaction: SELECT expired rows, write
    the cold file, then DELETE the selected ids. The file write happens
    BEFORE the delete; if it raises, the transaction rolls back untouched
    and the error propagates -- SQLite is never left missing rows that the
    cold store doesn't hold.
    """
    unknown = [t for t in tables if t not in _TS_COLUMNS]
    if unknown:
        raise ValueError(f"unknown table(s) {unknown}; archivable: {sorted(_TS_COLUMNS)}")
    if not hasattr(world, "_writing"):
        raise TypeError("archive() requires the SQLite WorldModel backend")
    cutoff = cutoff_epoch(older_than_days)
    cold = Path(cold_dir).expanduser()
    cold.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(cold, 0o700)  # cold rows carry the content world.db protects
    except OSError:
        pass
    rows_archived: dict[str, int] = {}
    files: list[Path] = []
    for table in tables:
        ts_col = _TS_COLUMNS[table]
        pin = _PIN_FILTERS.get(table, "")
        with world._writing() as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    f"SELECT * FROM {table} WHERE {ts_col} < ?{pin} ORDER BY {ts_col}, id",
                    (cutoff,),
                ).fetchall()
            ]
            if not rows:
                rows_archived[table] = 0
                continue
            path = _write_cold_file(cold, table, ts_col, rows)
            ids = [r["id"] for r in rows]
            for i in range(0, len(ids), _DELETE_CHUNK):
                chunk = ids[i:i + _DELETE_CHUNK]
                conn.execute(
                    f"DELETE FROM {table} WHERE id IN ({','.join('?' * len(chunk))})",
                    chunk,
                )
        rows_archived[table] = len(rows)
        files.append(path)
        log.info("tiered storage: archived %d %s row(s) -> %s", len(rows), table, path)
    return ArchiveResult(rows_archived=rows_archived, files=files)


def _read_jsonl_gz(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _read_jsonl_zst(path: Path) -> Iterator[dict]:
    try:
        zstd = importlib.import_module("zstandard")
    except Exception as exc:
        raise RuntimeError(
            f"{path.name} is zstd but zstandard is not importable; "
            "install the [zstd] extra to read it"
        ) from exc
    dctx = zstd.ZstdDecompressor()
    with open(path, "rb") as raw, dctx.stream_reader(raw) as reader:
        for line in io.TextIOWrapper(reader, encoding="utf-8"):
            line = line.strip()
            if line:
                yield json.loads(line)


def _read_parquet(path: Path) -> Iterator[dict]:
    try:
        papq = importlib.import_module("pyarrow.parquet")
    except Exception as exc:
        raise RuntimeError(
            f"{path.name} is parquet but pyarrow is not importable; "
            "install the [pandas] extra to read it"
        ) from exc
    yield from papq.read_table(str(path)).to_pylist()


def read_cold(cold_dir: str | Path, table: str) -> Iterator[dict]:
    """Iterate archived rows of ``table`` as dicts, file-name order.

    Reads every cold format (``.parquet``, ``.jsonl.gz``, ``.jsonl.zst``); a
    missing or empty directory yields nothing. Parquet/zstd need their
    optional dep to read back -- a clear ``RuntimeError`` says so instead of a
    bare import failure. A mixed directory (codec changed between runs) reads
    fine.
    """
    cold = Path(cold_dir).expanduser()
    # De-dup by row id so cold reads are IDEMPOTENT. archive() durably renames a
    # cold file BEFORE its DELETE commits (the no-data-loss direction), so a
    # crash in between leaves the rows in SQLite *and* the cold file; the next
    # archive() then re-writes them to a second file (`-2`). Without this dedup,
    # read_cold would yield those rows twice and double-count archived analytics.
    seen_ids: set = set()
    for path in sorted(cold.glob(f"{table}-*")):
        if path.name.endswith(".jsonl.gz"):
            reader = _read_jsonl_gz(path)
        elif path.name.endswith(".jsonl.zst"):
            reader = _read_jsonl_zst(path)
        elif path.name.endswith(".parquet"):
            reader = _read_parquet(path)
        else:
            # anything else (e.g. an orphaned .tmp) is not cold data: skip it
            continue
        for row in reader:
            rid = row.get("id")
            if rid is not None:
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
            yield row


def _world_cfg() -> dict:
    try:
        from .config import load_config
        return (load_config() or {}).get("world_model", {}) or {}
    except Exception:  # pragma: no cover -- config never blocks archival
        return {}


def configured_archive(world) -> ArchiveResult | None:
    """Run :func:`archive` with the configured knobs; ``None`` when unset.

    Reads ``[world_model] cold_dir`` + ``archive_after_days`` (env overrides:
    ``MAVERICK_WORLD_COLD_DIR`` / ``MAVERICK_WORLD_ARCHIVE_AFTER_DAYS``).
    Both must be set and ``archive_after_days`` must be a number > 0 --
    anything else is a no-op, so the feature stays off by default and a
    config typo can't silently archive everything. Never auto-runs; the
    operator/cron invokes it.
    """
    cfg = _world_cfg()
    cold_dir = os.environ.get("MAVERICK_WORLD_COLD_DIR", "").strip() or cfg.get("cold_dir")
    raw_days = (
        os.environ.get("MAVERICK_WORLD_ARCHIVE_AFTER_DAYS", "").strip()
        or cfg.get("archive_after_days")
    )
    if not cold_dir or raw_days in (None, ""):
        return None
    try:
        days = float(raw_days)
    except (TypeError, ValueError):
        log.warning("tiered storage: ignoring non-numeric archive_after_days=%r", raw_days)
        return None
    if days <= 0:
        log.warning("tiered storage: archive_after_days must be > 0 (got %r); skipping", days)
        return None
    return archive(world, older_than_days=days, cold_dir=Path(str(cold_dir)).expanduser())


__all__ = ["ArchiveResult", "archive", "configured_archive", "cutoff_epoch", "read_cold"]
