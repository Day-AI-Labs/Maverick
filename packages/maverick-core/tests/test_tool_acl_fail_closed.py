"""tool_acl fails CLOSED for a restricted principal when config can't be read.

A transiently unreadable config.toml (partial write, bad perms) must not drop a
per-channel/per-user deny-list or risk ceiling and silently hand the agent full
tool access. With a channel/user context we deny instead; with no such context
(global) behaviour is unchanged (fail-open, since a fully unreadable config
already breaks the whole deployment)."""
from __future__ import annotations

import pytest
from maverick.safety import tool_acl


@pytest.fixture
def _broken_config(monkeypatch):
    def _boom():
        raise OSError("config.toml unreadable")
    monkeypatch.setattr("maverick.config.load_config", _boom)


# ---- per-principal loaders -----------------------------------------------


def test_channel_load_fails_closed(_broken_config):
    allowed, denied = tool_acl._load_lists_for_channel("slack")
    assert allowed == set(tool_acl._FAIL_CLOSED)  # no real tool satisfies it


def test_user_load_fails_closed(_broken_config):
    allowed, _ = tool_acl._load_lists_for_user("slack:U1")
    assert allowed == set(tool_acl._FAIL_CLOSED)


def test_global_load_stays_fail_open(_broken_config):
    # No channel/user context -> the existing fail-open behaviour (empty lists).
    assert tool_acl._load_lists() == (set(), set())


# ---- composition: a restricted principal ends up with NO tools ------------


def test_resolve_lists_denies_all_when_restricted_and_config_unreadable(_broken_config):
    allowed, denied = tool_acl.resolve_lists(channel="slack", user_id="slack:U1")
    kept = tool_acl.filter_tools({"read_file", "shell", "http_fetch"},
                                 allowed=allowed, denied=denied)
    assert kept == set()  # fail closed: nothing survives


def test_apply_to_registry_strips_all_when_restricted(_broken_config):
    class _Tool:
        def __init__(self, name):
            self.name = name

    class _Reg:
        def __init__(self):
            self._tools = {n: _Tool(n) for n in ("read_file", "shell")}

        def all(self):
            return list(self._tools.values())

        def set_acl(self, **_kw):
            pass

    reg = _Reg()
    tool_acl.apply_to_registry(reg, channel="slack", user_id="slack:U1")
    assert reg._tools == {}  # every tool dropped


# ---- max_risk ceiling -----------------------------------------------------


def test_max_risk_fails_closed_to_tightest_when_restricted(_broken_config):
    from maverick.safety.tool_risk import RISK_LEVELS, risk_rank
    tightest = min(RISK_LEVELS, key=risk_rank)
    assert tool_acl.resolve_max_risk(channel="slack") == tightest
    assert tool_acl.resolve_max_risk(user_id="slack:U1") == tightest


def test_max_risk_unrestricted_stays_none(_broken_config):
    assert tool_acl.resolve_max_risk() is None
