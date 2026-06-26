"""Backup / restore / DR for a single-client deployment.

One Maverick per enterprise client (single-node + HA failover), so disaster
recovery is "snapshot this client's whole state, ship it, restore it on a
standby." This module snapshots the **client-scoped data root** (``data_dir()``
— under ``tenants/<client>/`` when bound), so a backup contains exactly one
client's data and can never reintroduce another's:

* the world DB (and any ``*.db``) is copied via the SQLite **online backup API**
  so the snapshot is consistent even under concurrent writers / WAL;
* the signed **audit chain** (ndjson + anchors) and **keys**, cross-session
  memory, fleet memory, and the managed trust registry come along verbatim;
* a ``manifest.json`` records the client id, timestamp, world schema version,
  and a SHA-256 per file for integrity + a cross-client restore guard.

Restore is **fail-closed**: it refuses to restore a backup whose ``client_id``
differs from the live deployment's (unless ``force=True``), and extraction
rejects path traversal / absolute / symlink members (mirrors
``workspace_snapshot``), so a tarball can't escape the data root.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import tarfile
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

MANIFEST = "manifest.json"
SCHEMA = 1
# Ephemeral SQLite sidecars — the consistent .db copy already contains their
# content, so snapshotting them would be redundant and racy.
_SKIP_SUFFIXES = ("-wal", "-shm", ".tmp")


class BackupError(RuntimeError):
    """A backup cannot be created or a restore cannot be safely applied."""


def _client_root() -> Path:
    from .paths import data_dir
    return data_dir()


def _client_id() -> str | None:
    from .client import client_id
    return client_id()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _consistent_db_copy(src: Path, dst: Path) -> None:
    """Copy a SQLite DB via the online backup API (consistent under WAL)."""
    s = sqlite3.connect(str(src))
    try:
        d = sqlite3.connect(str(dst))
        try:
            s.backup(d)
        finally:
            d.close()
    finally:
        s.close()


def _world_schema_version(root: Path) -> int | None:
    db = root / "world.db"
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(str(db))
        try:
            row = con.execute("SELECT MAX(version) FROM schema_version").fetchone()
            return int(row[0]) if row and row[0] is not None else None
        finally:
            con.close()
    except sqlite3.Error:
        return None


def _stage(root: Path, stage: Path) -> None:
    """Copy the client data tree into ``stage``; ``*.db`` via the backup API.

    The ``backups/`` subtree is excluded: it lives under the client root, so
    without this every new backup would sweep in all prior ``.tgz`` files and
    grow quadratically (a backup containing every earlier backup).
    """
    backups_dir = data_backups_dir().resolve()
    for src in sorted(root.rglob("*")):
        if src.is_symlink() or not src.is_file():
            continue
        if src.name.endswith(_SKIP_SUFFIXES):
            continue
        if backups_dir in src.resolve().parents:
            continue
        rel = src.relative_to(root)
        dst = stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".db":
            _consistent_db_copy(src, dst)
        else:
            dst.write_bytes(src.read_bytes())
        os.chmod(dst, 0o600)


def create_backup(out: str | Path | None = None) -> Path:
    """Snapshot this client's data root to a ``.tgz``. Returns the path.

    ``out`` is the destination file (default
    ``data_dir("backups")/maverick-<client>-<ts>.tgz``). Raises
    :class:`BackupError` if there is nothing to back up.
    """
    root = _client_root()
    if not root.exists():
        raise BackupError(f"no data root to back up at {root}")
    cid = _client_id() or "unbound"
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    if out is None:
        out = data_backups_dir() / f"maverick-{cid}-{ts}.tgz"
    out = Path(out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="mvk-backup-") as td:
        stage = Path(td) / "data"
        stage.mkdir()
        # Snapshot the world schema version BEFORE staging (off the live DB).
        schema_v = _world_schema_version(root)
        _stage(root, stage)
        files = {
            str(p.relative_to(stage)): _sha256(p)
            for p in sorted(stage.rglob("*")) if p.is_file()
        }
        manifest = {
            "schema": SCHEMA,
            "client_id": _client_id(),
            "created_at": time.time(),
            "world_schema_version": schema_v,
            "files": files,
        }
        (Path(td) / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True))
        # Atomic write: build to a temp then rename into place.
        tmp_out = out.with_suffix(out.suffix + ".part")
        with tarfile.open(tmp_out, "w:gz") as tar:
            tar.add(Path(td) / MANIFEST, arcname=MANIFEST)
            tar.add(stage, arcname="data")
        os.chmod(tmp_out, 0o600)
        # fsync the tarball before the rename: os.replace is atomic for
        # VISIBILITY, but on a power-loss the rename can be durable while the
        # file contents are not -- yielding a zero/short backup at the final
        # name, exactly the DR artifact you reach for after a crash. Flush the
        # bytes (and the parent dir entry) so a present backup is a complete one.
        with open(tmp_out, "rb") as _f:
            os.fsync(_f.fileno())
        os.replace(tmp_out, out)
        try:
            dir_fd = os.open(str(out.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:  # pragma: no cover -- dir fsync unsupported on some FS
            pass
    log.info("backup written: %s (%d files, client=%s)", out, len(files), cid)
    return out


def data_backups_dir() -> Path:
    from .paths import data_dir
    return data_dir("backups")


def read_manifest(tarball: str | Path) -> dict:
    """Return the manifest from a backup tarball (raises on a bad archive)."""
    try:
        with tarfile.open(str(tarball), "r:gz") as tar:
            m = tar.extractfile(MANIFEST)
            if m is None:
                raise BackupError("backup has no manifest.json")
            return json.loads(m.read().decode("utf-8"))
    except (tarfile.TarError, OSError, ValueError) as e:
        raise BackupError(f"unreadable backup {tarball!r}: {e}") from e


def restore_backup(tarball: str | Path, *, force: bool = False) -> Path:
    """Restore a backup into this client's data root. Returns the root.

    Fail-closed cross-client guard: refuses when the backup's ``client_id``
    differs from the live deployment's, unless ``force=True`` (so acme's backup
    is never restored into beta's deployment by mistake). Extraction is
    path-traversal safe.
    """
    manifest = read_manifest(tarball)
    backup_cid = manifest.get("client_id")
    live_cid = _client_id()
    if not force and backup_cid != live_cid:
        raise BackupError(
            f"backup is for client {backup_cid!r} but this deployment is "
            f"{live_cid!r}; refusing (pass force=True to override)"
        )
    # Schema-version guard (the HA-failover path). Restoring a backup taken on a
    # NEWER binary (forward-migrated world.db) onto an OLDER binary would let the
    # old code open a DB schema it doesn't understand — silent corruption. Refuse
    # forward restores unless forced; older/equal schemas are fine (the world
    # DB's own migration upgrades them on open).
    from .world_model import SCHEMA_VERSION
    backup_schema_v = manifest.get("world_schema_version")
    if (not force and isinstance(backup_schema_v, int)
            and backup_schema_v > SCHEMA_VERSION):
        raise BackupError(
            f"backup world schema v{backup_schema_v} is newer than this "
            f"binary's v{SCHEMA_VERSION}; restoring it would corrupt the world "
            f"DB. Upgrade Maverick first, or pass force=True to override."
        )
    expected = manifest.get("files") or {}
    root = _client_root()
    root.mkdir(parents=True, exist_ok=True)
    root_resolved = root.resolve()
    with tarfile.open(str(tarball), "r:gz") as tar, \
            tempfile.TemporaryDirectory(prefix="mvk-restore-") as td:
        # Validate member names BEFORE extracting (Python <3.12 extractall has
        # no traversal guard): a normalised name must stay within data/.
        safe = []
        for m in tar.getmembers():
            if not m.isfile() or m.issym() or m.islnk():
                continue
            if not m.name.startswith("data/"):
                continue  # non-payload member (manifest.json); not restored
            # A literal data/ prefix that NORMALISES outside data/ is an attack.
            norm = os.path.normpath(m.name)
            if not norm.startswith("data" + os.sep):
                raise BackupError(f"unsafe path in backup: {m.name!r}")
            safe.append(m)
        tar.extractall(td, members=safe)
        staged = Path(td) / "data"
        if not staged.exists():
            raise BackupError("backup contains no data/ payload")
        # Verify EVERYTHING in the staging area before touching the live root:
        # integrity (recorded SHA-256 per file) + traversal. Only once the whole
        # payload validates do we copy it in, so a corrupt/truncated backup never
        # half-overwrites a live deployment (verify-then-write).
        staged_files = [p for p in sorted(staged.rglob("*")) if p.is_file()]
        for src in staged_files:
            rel = src.relative_to(staged)
            dst = root / rel
            if dst.resolve() != root_resolved and root_resolved not in dst.resolve().parents:
                raise BackupError(f"unsafe restore path: {rel}")
            # The manifest is an EXHAUSTIVE allow-list: create_backup records a
            # SHA-256 for every staged file, so a payload file with no manifest
            # entry is not a legitimate backup -- it's a corrupt/tampered archive
            # smuggling an unverified file into the live root. Reject it rather
            # than write it through unchecked (the old `want is not None` guard
            # silently skipped integrity for unlisted files).
            want = expected.get(str(rel))
            if want is None:
                raise BackupError(
                    f"backup payload {rel} is not in the manifest "
                    f"(backup is corrupt or tampered)"
                )
            if _sha256(src) != want:
                raise BackupError(
                    f"backup integrity check failed for {rel} "
                    f"(SHA-256 mismatch — backup is corrupt or truncated)"
                )
        for src in staged_files:
            dst = root / src.relative_to(staged)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            os.chmod(dst, 0o600)
    log.info("restore complete into %s (from client=%s, %d files verified)",
             root, backup_cid, len(staged_files))
    return root


__all__ = [
    "BackupError",
    "create_backup",
    "restore_backup",
    "read_manifest",
    "data_backups_dir",
]
