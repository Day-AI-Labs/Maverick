"""MCP server registry: discovery + install + config mutation (ROADMAP B2)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from maverick import catalog, mcp_registry
from maverick.mcp_client import MCPServerSpec


def _toml_load(path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    with open(path, "rb") as f:
        return tomllib.load(f)


_FAKE_INDEX = {
    "schema_version": 1,
    "kind": "mcp",
    "entries": [
        {"name": "github", "version": "1.0.0", "summary": "GitHub MCP server",
         "author": "acme", "verified": True,
         "spec": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                  "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}}},
        {"name": "remote-thing", "version": "2.0.0", "summary": "A remote HTTP MCP",
         "spec": {"url": "https://mcp.example.com/sse",
                  "headers": {"X-Tenant": "acme"}}},
    ],
}


@pytest.fixture
def fake_registry(monkeypatch):
    # Drive the real load_catalog path with a fixed index (no network).
    monkeypatch.setattr(catalog, "_fetch_index_raw", lambda url: _FAKE_INDEX)
    return ["https://registry.test"]


# ---- catalog inline-spec entry ----------------------------------------------

def test_catalog_entry_carries_inline_spec_without_source():
    e = catalog.CatalogEntry.from_dict("mcp", {
        "name": "x", "spec": {"command": "echo"}})
    assert e.spec == {"command": "echo"} and e.source == ""
    # Round-trips through to_dict (spec included only when non-empty).
    assert e.to_dict()["spec"] == {"command": "echo"}
    assert "spec" not in catalog.CatalogEntry.from_dict(
        "skills", {"name": "s", "source": "gh:o/r:S.md", "sha256": "ab"}).to_dict()


def test_catalog_entry_requires_name_and_source_or_spec():
    with pytest.raises(catalog.CatalogError):
        catalog.CatalogEntry.from_dict("mcp", {"name": "x"})  # neither source nor spec


# ---- MCPServerSpec.to_dict round-trip ---------------------------------------

def test_spec_to_dict_roundtrip_stdio():
    spec = MCPServerSpec(name="github", command="npx", args=["-y", "pkg"],
                         env={"GITHUB_TOKEN": "x"}, pin_sha256="deadbeef")
    d = spec.to_dict()
    assert d == {"command": "npx", "args": ["-y", "pkg"],
                 "env": {"GITHUB_TOKEN": "x"}, "pin_sha256": "deadbeef"}
    # from_config(to_dict()) reconstructs the same spec.
    assert MCPServerSpec.from_config("github", d) == spec


def test_spec_to_dict_roundtrip_http():
    spec = MCPServerSpec(name="r", url="https://h/sse", headers={"A": "b"},
                         auth_token="tok")
    d = spec.to_dict()
    assert d == {"url": "https://h/sse", "headers": {"A": "b"}, "auth_token": "tok"}
    assert MCPServerSpec.from_config("r", d) == spec


# ---- registry discovery + install -------------------------------------------

def test_load_and_resolve(fake_registry):
    names = {e.name for e in mcp_registry.load_mcp_registry(indexes=fake_registry)}
    assert names == {"github", "remote-thing"}
    assert mcp_registry.resolve_mcp("github", indexes=fake_registry).verified is True
    assert mcp_registry.resolve_mcp("absent", indexes=fake_registry) is None


def test_install_builds_validated_spec(fake_registry):
    spec = mcp_registry.install_mcp_from_registry("github", indexes=fake_registry)
    assert spec.command == "npx" and spec.args[0] == "-y"
    http = mcp_registry.install_mcp_from_registry("remote-thing", indexes=fake_registry)
    assert http.is_http and http.url == "https://mcp.example.com/sse"


def test_install_unknown_name_raises(fake_registry):
    with pytest.raises(ValueError, match="no MCP server"):
        mcp_registry.install_mcp_from_registry("nope", indexes=fake_registry)


def test_install_rejects_unsafe_spec(monkeypatch):
    # A registry entry whose command smuggles a shell metacharacter must be
    # rejected by MCPServerSpec validation (CVE-2026-30615 class), not installed.
    bad = {"schema_version": 1, "kind": "mcp", "entries": [
        {"name": "evil", "spec": {"command": "sh -c 'rm -rf ~'; echo"}}]}
    monkeypatch.setattr(catalog, "_fetch_index_raw", lambda url: bad)
    with pytest.raises(ValueError):
        mcp_registry.install_mcp_from_registry("evil", indexes=["https://x.test"])


# ---- config mutation --------------------------------------------------------

def test_add_then_remove_config(tmp_path):
    cfg = tmp_path / "config.toml"
    mcp_registry.add_mcp_server_to_config(
        "github", {"command": "npx", "args": ["-y", "pkg"],
                   "env": {"GITHUB_TOKEN": "x"}}, path=cfg)
    parsed = _toml_load(cfg)
    assert parsed["mcp_servers"]["github"]["command"] == "npx"
    assert parsed["mcp_servers"]["github"]["env"] == {"GITHUB_TOKEN": "x"}
    # Re-adding the same name is refused.
    with pytest.raises(ValueError, match="already in config"):
        mcp_registry.add_mcp_server_to_config("github", {"command": "x"}, path=cfg)
    # Remove it.
    assert mcp_registry.remove_mcp_server_from_config("github", path=cfg) is True
    assert "github" not in (_toml_load(cfg).get("mcp_servers") or {})
    # Removing again is a no-op.
    assert mcp_registry.remove_mcp_server_from_config("github", path=cfg) is False


def test_add_preserves_unrelated_config(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[budget]\nmax_dollars = 5.0\n\n[mcp_servers.keep]\ncommand = "old"\n',
                   encoding="utf-8")
    mcp_registry.add_mcp_server_to_config(
        "remote", {"url": "https://h/sse", "headers": {"A": "b"}}, path=cfg)
    parsed = _toml_load(cfg)
    # The new server, the pre-existing server, and the unrelated table all survive.
    assert parsed["budget"]["max_dollars"] == 5.0
    assert parsed["mcp_servers"]["keep"]["command"] == "old"
    assert parsed["mcp_servers"]["remote"]["url"] == "https://h/sse"
    assert parsed["mcp_servers"]["remote"]["headers"] == {"A": "b"}


def test_remove_preserves_unrelated_config(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[budget]\nmax_dollars = 5.0\n\n'
        '[mcp_servers.drop]\ncommand = "x"\n\n'
        '[mcp_servers.keep]\ncommand = "y"\n', encoding="utf-8")
    assert mcp_registry.remove_mcp_server_from_config("drop", path=cfg) is True
    parsed = _toml_load(cfg)
    assert "drop" not in parsed["mcp_servers"]
    assert parsed["mcp_servers"]["keep"]["command"] == "y"
    assert parsed["budget"]["max_dollars"] == 5.0


def test_install_to_config_roundtrip(tmp_path, fake_registry):
    # End to end: resolve from registry -> validated spec -> write -> read back
    # -> same spec via the loader path the kernel uses.
    cfg = tmp_path / "config.toml"
    spec = mcp_registry.install_mcp_from_registry("github", indexes=fake_registry)
    mcp_registry.add_mcp_server_to_config(spec.name, spec.to_dict(), path=cfg)
    server_cfg = _toml_load(cfg)["mcp_servers"]["github"]
    assert MCPServerSpec.from_config("github", server_cfg) == spec
