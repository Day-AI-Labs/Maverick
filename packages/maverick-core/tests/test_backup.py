"""Backup / restore / DR for a single-client deployment: consistent snapshot of
the client data root, round-trip restore, the cross-client fail-closed guard,
and path-traversal-safe extraction."""
from __future__ import annotations

import sqlite3
import tarfile

import pytest
from maverick import backup, client


@pytest.fixture(autouse=True)
def _bound_client(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_CLIENT_ID", "acme")
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    client.reset_client_cache()
    yield
    client.reset_client_cache()


def _seed(root):
    """Write a tiny world DB + audit-ish files into the client data root."""
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(root / "world.db"))
    con.execute("CREATE TABLE t (v TEXT)")
    con.execute("INSERT INTO t VALUES ('secret-data')")
    con.commit()
    con.close()
    (root / "audit").mkdir(exist_ok=True)
    (root / "audit" / "2026-06-18.ndjson").write_text('{"kind":"x"}\n')
    (root / "agent_trust.json").write_text('[{"id":"vega"}]')


def test_create_and_restore_round_trip():
    from maverick.paths import data_dir
    root = data_dir()
    _seed(root)
    tar = backup.create_backup()
    assert tar.exists()

    # Wipe + restore.
    (root / "world.db").unlink()
    (root / "agent_trust.json").unlink()
    backup.restore_backup(tar)

    con = sqlite3.connect(str(root / "world.db"))
    assert con.execute("SELECT v FROM t").fetchone()[0] == "secret-data"
    con.close()
    assert (root / "agent_trust.json").read_text() == '[{"id":"vega"}]'


def test_manifest_records_client():
    from maverick.paths import data_dir
    _seed(data_dir())
    tar = backup.create_backup()
    m = backup.read_manifest(tar)
    assert m["client_id"] == "acme" and m["schema"] == 1
    assert "world.db" in m["files"]


def test_restore_refuses_cross_client(monkeypatch):
    from maverick.paths import data_dir
    _seed(data_dir())
    tar = backup.create_backup()  # client_id = acme
    # Now this deployment is a DIFFERENT client.
    monkeypatch.setenv("MAVERICK_CLIENT_ID", "beta")
    client.reset_client_cache()
    with pytest.raises(backup.BackupError):
        backup.restore_backup(tar)
    # force overrides.
    backup.restore_backup(tar, force=True)


def test_restore_rejects_file_not_in_manifest(tmp_path):
    # The manifest is an exhaustive allow-list. A payload file with no manifest
    # entry (and thus no recorded SHA-256) is a corrupt/tampered archive trying
    # to write an unverified file into the live root; restore must reject it,
    # not silently pass it through (the old `want is not None` guard skipped it).
    from maverick.paths import data_dir
    _seed(data_dir())
    tar = backup.create_backup()

    tampered = tmp_path / "tampered.tgz"
    extra = tmp_path / "sneaky"
    extra.write_text("unverified payload")
    with tarfile.open(tar, "r:gz") as src, tarfile.open(tampered, "w:gz") as dst:
        for m in src.getmembers():
            dst.addfile(m, src.extractfile(m) if m.isfile() else None)
        dst.add(extra, arcname="data/sneaky.txt")

    with pytest.raises(backup.BackupError, match="not in the manifest"):
        backup.restore_backup(tampered)


def test_restore_rejects_path_traversal(tmp_path):
    # Hand-craft a malicious tarball with a ../ member.
    bad = tmp_path / "evil.tgz"
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "x").write_text("data")
    import json
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema": 1, "client_id": "acme", "files": {}}))
    with tarfile.open(bad, "w:gz") as tar:
        tar.add(manifest, arcname="manifest.json")
        tar.add(payload / "x", arcname="data/../../escape")
    with pytest.raises(backup.BackupError):
        backup.restore_backup(bad)


def test_backup_excludes_prior_backups(monkeypatch):
    """The backups/ subtree lives under the client root; it must NOT be swept
    into a new backup, or each backup would contain every earlier one and grow
    quadratically."""
    from maverick.paths import data_dir
    _seed(data_dir())
    first = backup.create_backup()
    assert first.exists()
    # A second backup must not contain the first .tgz under data/backups/.
    second = backup.create_backup()
    with tarfile.open(second, "r:gz") as tar:
        members = tar.getnames()
    assert not any(name.startswith("data/backups/") for name in members), members
    assert "data/world.db" in members


def _repack(src_tar, dst_tar, *, mutate_manifest=None, mutate_data=None):
    """Rebuild a backup tarball, optionally mutating the manifest dict or a
    named data file's bytes — to forge corrupt / schema-incompatible backups."""
    import io
    import json
    with tarfile.open(src_tar, "r:gz") as t:
        members = t.getmembers()
        blobs = {m.name: (t.extractfile(m).read() if m.isfile() else None) for m in members}
    manifest = json.loads(blobs["manifest.json"].decode())
    if mutate_manifest:
        mutate_manifest(manifest)
    blobs["manifest.json"] = json.dumps(manifest).encode()
    if mutate_data:
        name, data = mutate_data
        blobs[name] = data
    with tarfile.open(dst_tar, "w:gz") as t:
        for m in members:
            if not m.isfile():
                continue
            info = tarfile.TarInfo(m.name)
            info.size = len(blobs[m.name])
            t.addfile(info, io.BytesIO(blobs[m.name]))


def test_restore_refuses_forward_schema(tmp_path, monkeypatch):
    from maverick.paths import data_dir
    from maverick.world_model import SCHEMA_VERSION
    _seed(data_dir())
    tar = backup.create_backup()
    forward = tmp_path / "forward.tgz"
    _repack(tar, forward,
            mutate_manifest=lambda m: m.update(world_schema_version=SCHEMA_VERSION + 5))
    (data_dir() / "world.db").unlink()
    with pytest.raises(backup.BackupError, match="newer than this binary"):
        backup.restore_backup(forward)
    # force overrides the guard.
    backup.restore_backup(forward, force=True)


def test_restore_detects_corruption(tmp_path):
    from maverick.paths import data_dir
    _seed(data_dir())
    tar = backup.create_backup()
    corrupt = tmp_path / "corrupt.tgz"
    # Flip the agent_trust.json bytes but keep the manifest's recorded SHA-256.
    _repack(tar, corrupt, mutate_data=("data/agent_trust.json", b"TAMPERED"))
    original = (data_dir() / "agent_trust.json").read_text()
    with pytest.raises(backup.BackupError, match="integrity check failed"):
        backup.restore_backup(corrupt)
    # Verify-then-write: the live root was NOT partially overwritten.
    assert (data_dir() / "agent_trust.json").read_text() == original


def test_restore_clears_stale_wal_sidecar():
    """DR scenario: a stale, uncheckpointed world.db-wal in the live root must
    NOT survive a restore and replay post-backup mutations back over the
    restored DB. Backups exclude the -wal/-shm sidecars on purpose (the
    consistent .db copy already folds them in), so restore is responsible for
    removing any pre-existing ones in the live root."""
    from maverick.paths import data_dir
    root = data_dir()

    # Baseline world.db (WAL mode, fully checkpointed) holding only the content
    # the backup will capture.
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(root / "world.db"))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (v TEXT)")
    con.execute("INSERT INTO t VALUES ('secret-data')")
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    (root / "agent_trust.json").write_text('[{"id":"vega"}]')

    tar = backup.create_backup()  # snapshots the clean baseline only

    # A post-backup mutation that lives ONLY in the WAL (never checkpointed):
    # keep the connection open so SQLite cannot checkpoint, capture the live
    # sidecar bytes, then close. Writing those bytes back recreates exactly the
    # post-crash stale-WAL-on-disk state (close-time checkpoint truncates it,
    # so we must reconstruct it to model the hard-crash case).
    con = sqlite3.connect(str(root / "world.db"))
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("INSERT INTO t VALUES ('post-backup-mutation')")
    con.commit()
    wal_bytes = (root / "world.db-wal").read_bytes()
    shm_path = root / "world.db-shm"
    shm_bytes = shm_path.read_bytes() if shm_path.exists() else None
    assert wal_bytes, "test needs a non-empty stale WAL"
    con.close()
    (root / "world.db-wal").write_bytes(wal_bytes)
    if shm_bytes is not None:
        shm_path.write_bytes(shm_bytes)
    assert (root / "world.db-wal").stat().st_size > 0

    backup.restore_backup(tar, force=True)

    # The stale WAL must be gone, and reopening must show ONLY the backed-up
    # content — the post-backup mutation must not have been replayed back in.
    assert not (root / "world.db-wal").exists()
    con = sqlite3.connect(str(root / "world.db"))
    rows = {r[0] for r in con.execute("SELECT v FROM t").fetchall()}
    con.close()
    assert rows == {"secret-data"}, rows


def test_create_errors_when_no_data(monkeypatch, tmp_path):
    # Point at an empty home with a fresh client -> no data root.
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "empty"))
    client.reset_client_cache()
    with pytest.raises(backup.BackupError):
        backup.create_backup()


def test_cli_backup_create_info_restore():
    from click.testing import CliRunner
    from maverick.cli import main
    from maverick.paths import data_dir
    _seed(data_dir())
    runner = CliRunner()

    r = runner.invoke(main, ["backup", "create"])
    assert r.exit_code == 0 and "backup written" in r.output
    tarball = r.output.split("backup written:")[1].strip()

    r = runner.invoke(main, ["backup", "info", tarball])
    assert r.exit_code == 0 and "acme" in r.output

    (data_dir() / "world.db").unlink()
    r = runner.invoke(main, ["backup", "restore", tarball])
    assert r.exit_code == 0 and "restored into" in r.output
    assert (data_dir() / "world.db").exists()
