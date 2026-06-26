"""Backup / restore / DR for a single-client deployment: consistent snapshot of
the client data root, round-trip restore, the cross-client fail-closed guard,
and path-traversal-safe extraction."""
from __future__ import annotations

import json
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


def test_restore_rejects_path_traversal(tmp_path):
    # Hand-craft a malicious tarball with a ../ member.
    bad = tmp_path / "evil.tgz"
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "x").write_text("data")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema": 1, "client_id": "acme", "files": {"x": "0" * 64}}))
    with tarfile.open(bad, "w:gz") as tar:
        tar.add(manifest, arcname="manifest.json")
        tar.add(payload / "x", arcname="data/../../escape")
    with pytest.raises(backup.BackupError):
        backup.restore_backup(bad)


def test_restore_rejects_tampered_payload(tmp_path):
    from maverick.paths import data_dir

    root = data_dir()
    _seed(root)
    original = backup.create_backup()
    bad = tmp_path / "tampered.tgz"
    tampered = tmp_path / "agent_trust.json"
    tampered.write_text('[{"id":"attacker","role":"trusted"}]')

    with tarfile.open(original, "r:gz") as src, tarfile.open(bad, "w:gz") as dst:
        for member in src.getmembers():
            if member.name == "data/agent_trust.json":
                dst.add(tampered, arcname=member.name)
                continue
            extracted = src.extractfile(member) if member.isfile() else None
            dst.addfile(member, extracted)

    (root / "agent_trust.json").write_text('[{"id":"live"}]')
    with pytest.raises(backup.BackupError, match="hash mismatch"):
        backup.restore_backup(bad)
    assert (root / "agent_trust.json").read_text() == '[{"id":"live"}]'


def test_restore_rejects_extra_payload_file(tmp_path):
    from maverick.paths import data_dir

    _seed(data_dir())
    original = backup.create_backup()
    bad = tmp_path / "extra.tgz"
    extra = tmp_path / "extra.txt"
    extra.write_text("surprise")

    with tarfile.open(original, "r:gz") as src, tarfile.open(bad, "w:gz") as dst:
        for member in src.getmembers():
            extracted = src.extractfile(member) if member.isfile() else None
            dst.addfile(member, extracted)
        dst.add(extra, arcname="data/extra.txt")

    with pytest.raises(backup.BackupError, match="does not match manifest"):
        backup.restore_backup(bad)


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
