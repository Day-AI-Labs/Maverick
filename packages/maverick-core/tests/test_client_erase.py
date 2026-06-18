"""Phase 6 — per-client export + right-to-erasure. Provably complete because one
deployment = one client = one data root; fail-closed so it never targets the
shared root."""
from __future__ import annotations

import pytest
from maverick import client


@pytest.fixture(autouse=True)
def _bound(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_CLIENT_ID", "acme")
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    client.reset_client_cache()
    yield
    client.reset_client_cache()


def _seed():
    import sqlite3

    from maverick.paths import data_dir
    root = data_dir()
    (root / "audit").mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(root / "world.db"))  # a real DB (export uses backup API)
    con.execute("CREATE TABLE t (v)")
    con.commit()
    con.close()
    (root / "audit" / "2026.ndjson").write_text("{}")
    (root / "agent_trust.json").write_text("[]")
    return root


def test_erase_removes_everything():
    root = _seed()
    res = client.erase_client()
    assert res["client_id"] == "acme" and res["removed"] >= 3
    assert not (root / "world.db").exists()
    assert not (root / "agent_trust.json").exists()
    assert not (root / "audit" / "2026.ndjson").exists()


def test_erase_keep_audit():
    root = _seed()
    client.erase_client(keep_audit=True)
    assert not (root / "world.db").exists()
    assert (root / "audit" / "2026.ndjson").exists()  # retained


def test_erase_refuses_without_binding(monkeypatch):
    monkeypatch.delenv("MAVERICK_CLIENT_ID", raising=False)
    monkeypatch.setattr(client, "_resolve", lambda: None)
    client.reset_client_cache()
    with pytest.raises(client.ClientBindingError):
        client.erase_client()


def test_erase_targets_client_subtree_only(monkeypatch, tmp_path):
    # A file directly under MAVERICK_HOME (the shared root) is NOT touched —
    # erase only wipes tenants/<client>/.
    _seed()
    shared = tmp_path / "shared.txt"
    shared.write_text("other")
    client.erase_client()
    assert shared.exists()


# ---- CLI ------------------------------------------------------------------


def _run(*args):
    from click.testing import CliRunner
    from maverick.cli import main
    return CliRunner().invoke(main, list(args))


def test_cli_erase_requires_confirm():
    _seed()
    r = _run("client", "erase")
    assert r.exit_code != 0 and "--confirm" in r.output
    from maverick.paths import data_dir
    assert (data_dir() / "world.db").exists()  # nothing erased without --confirm


def test_cli_status_and_erase_confirm():
    _seed()
    r = _run("client", "status")
    assert r.exit_code == 0 and "acme" in r.output
    r = _run("client", "erase", "--confirm")
    assert r.exit_code == 0 and "erased client" in r.output
    from maverick.paths import data_dir
    assert not (data_dir() / "world.db").exists()


def test_cli_export():
    _seed()
    r = _run("client", "export")
    assert r.exit_code == 0 and "client export written" in r.output
