"""`maverick trust` admin: the JSON managed-registry overlay (add/rotate/revoke
without editing TOML) and the CLI surface that drives it."""
from __future__ import annotations

import pytest
from maverick import agent_trust, client


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_CLIENT_ID", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    client.reset_client_cache()
    yield
    client.reset_client_cache()


# ---- managed registry overlay ---------------------------------------------


def test_put_and_load_merges_managed():
    agent_trust.put_agent({"id": "vega", "pubkey": "ab" * 32,
                           "allow_tools": ["read_file"], "direction": "both"})
    reg = agent_trust.load_registry({})  # config has no agents; managed supplies vega
    assert "vega" in reg
    assert reg["vega"].allow_tools == frozenset({"read_file"})


def test_put_replaces_same_id():
    agent_trust.put_agent({"id": "vega", "max_risk": "low"})
    agent_trust.put_agent({"id": "vega", "max_risk": "high"})
    reg = agent_trust.load_registry({})
    assert reg["vega"].max_risk == "high"
    # exactly one managed entry for vega
    assert sum(1 for e in agent_trust._load_managed() if e["id"] == "vega") == 1


def test_remove_agent():
    agent_trust.put_agent({"id": "vega"})
    assert agent_trust.remove_agent("vega") is True
    assert "vega" not in agent_trust.load_registry({})
    assert agent_trust.remove_agent("vega") is False


def test_revoke_blocks_via_is_active():
    agent_trust.put_agent({"id": "vega", "pubkey": "ab" * 32})
    assert agent_trust.set_revoked("vega", True) is True
    reg = agent_trust.load_registry({})
    assert reg["vega"].is_active()[0] is False
    d = agent_trust.decide_inbound("vega", registry=reg, enforced=True)
    assert d.denied and d.rule == "revoked"
    agent_trust.set_revoked("vega", False)
    assert agent_trust.load_registry({})["vega"].is_active()[0] is True


def test_managed_overrides_config_entry():
    cfg = {"agent_trust": {"agents": [{"id": "vega", "max_risk": "low"}]}}
    assert agent_trust.load_registry(cfg)["vega"].max_risk == "low"
    agent_trust.put_agent({"id": "vega", "max_risk": "high"})
    assert agent_trust.load_registry(cfg)["vega"].max_risk == "high"  # managed wins


def test_put_invalid_raises():
    with pytest.raises(agent_trust.AgentTrustError):
        agent_trust.put_agent({"id": "BAD ID"})


def test_managed_path_is_client_scoped(monkeypatch):
    monkeypatch.setenv("MAVERICK_CLIENT_ID", "acme")
    client.reset_client_cache()
    assert "tenants/acme" in str(agent_trust.managed_path()).replace("\\", "/")


def test_local_pubkey():
    pytest.importorskip("cryptography")
    pk = agent_trust.local_pubkey()
    assert isinstance(pk, str) and len(pk) == 64


# ---- CLI ------------------------------------------------------------------


def _run(*args):
    from click.testing import CliRunner
    from maverick.cli import main
    return CliRunner().invoke(main, list(args))


def test_cli_add_list_show_verify_revoke_rm():
    r = _run("trust", "add", "vega", "--pubkey", "ab" * 32,
             "--allow-tools", "read_file", "--max-risk", "medium",
             "--direction", "both")
    assert r.exit_code == 0 and "saved" in r.output

    r = _run("trust", "list")
    assert r.exit_code == 0 and "vega" in r.output

    r = _run("trust", "show", "vega")
    assert r.exit_code == 0 and "read_file" in r.output

    # verify replays the decision
    r = _run("trust", "verify", "vega", "--tools", "read_file")
    assert r.exit_code == 0 and "ALLOW" in r.output
    r = _run("trust", "verify", "vega", "--tools", "shell")
    assert r.exit_code == 0 and "DENY" in r.output

    r = _run("trust", "revoke", "vega")
    assert r.exit_code == 0 and "revoked" in r.output
    r = _run("trust", "verify", "vega")
    assert "DENY" in r.output and "revoked" in r.output

    r = _run("trust", "rm", "vega")
    assert r.exit_code == 0 and "removed" in r.output


def test_cli_show_unknown_errors():
    r = _run("trust", "show", "ghost")
    assert r.exit_code != 0


def test_cli_status_runs():
    r = _run("trust", "status")
    assert r.exit_code == 0 and "agent trust plane" in r.output
