"""Pin the defenses that keep Maverick clear of the MCP STDIO RCE class.

Audit (May 2026, prompted by OX Security's disclosure of a by-design RCE
class in MCP STDIO transports across official SDKs): Maverick acts as an
MCP *client* spawning servers from the operator's own ~/.maverick/config.toml.
The spawn path is already hardened:

  1. command resolved via shutil.which() -> a CWD-local binary can't shadow
     a bare command name (the classic stdio-spawn hijack);
  2. command must be a non-empty str, args a list[str], env a dict -> no
     injection of structured/non-string payloads;
  3. no shell=True anywhere -> argv is exec'd directly, no shell interpolation;
  4. config is sourced ONLY from $MAVERICK_CONFIG or ~/.maverick/config.toml,
     never a project-local/CWD file or a downloaded catalog.

These tests fail loudly if a refactor reintroduces the hole.
"""
from __future__ import annotations

import asyncio
import inspect

import maverick.mcp_client as mc
import maverick.config as config


def test_command_not_on_path_is_not_spawned():
    # A command that doesn't resolve on PATH must be skipped (None), never
    # spawned. Uses a deliberately bogus name.
    spec = {"command": "maverick-definitely-not-a-real-binary-xyz", "args": []}
    out = asyncio.run(mc._connect_one("evil", spec))
    assert out is None


def test_non_string_command_rejected():
    assert asyncio.run(mc._connect_one("x", {"command": ["sh", "-c", "evil"]})) is None
    assert asyncio.run(mc._connect_one("x", {"command": ""})) is None
    assert asyncio.run(mc._connect_one("x", {})) is None


def test_non_string_args_rejected():
    # args containing a non-string (or not a list) must be rejected before spawn.
    spec = {"command": "sh", "args": [{"$inject": "rm -rf /"}]}
    assert asyncio.run(mc._connect_one("x", spec)) is None
    spec2 = {"command": "sh", "args": "not-a-list"}
    assert asyncio.run(mc._connect_one("x", spec2)) is None


def test_source_has_no_shell_true_and_uses_which():
    """Static guard: the spawn path must keep shutil.which and must never
    use shell=True (which would make args injectable)."""
    src = inspect.getsource(mc)
    assert "shutil.which(" in src, "lost the PATH-resolution defense"
    assert "shell=True" not in src, "shell=True reintroduces arg-injection RCE"


def test_config_is_not_loaded_from_cwd_or_project():
    """The MCP server list comes from the operator's home config (or an
    explicit MAVERICK_CONFIG), never an attacker-plantable project/CWD file."""
    src = inspect.getsource(config.load_config)
    # Must reference the home config path or the explicit env override...
    assert (".maverick" in src) or ("MAVERICK_CONFIG" in src)
    # ...and must NOT silently read a project-local / CWD config.
    assert "getcwd" not in src
    assert "Path.cwd" not in src
