"""Session providers must be OFF unless explicitly opted in.

They drive a vendor's consumer chat UI with captured login cookies --
against the vendor's ToS, with real account-ban risk. The factory
(get_session_client) must fail closed so the capability can't run by
accident; an operator opts in via MAVERICK_ENABLE_SESSION_PROVIDERS=1 or
[session_providers] enabled = true.

Note: no autouse opt-in fixture here (unlike the other session test
modules) -- this module verifies the disabled state.
"""
from __future__ import annotations

import pytest

from maverick.session_providers import get_session_client


def test_disabled_by_default(tmp_path, monkeypatch):
    # Neither the env flag nor a config file -> disabled.
    monkeypatch.delenv("MAVERICK_ENABLE_SESSION_PROVIDERS", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # no ~/.maverick/config.toml here
    with pytest.raises(RuntimeError, match="disabled"):
        get_session_client("claude-session")


def test_env_opt_in_passes_the_gate(tmp_path, monkeypatch):
    # With the opt-in set, the gate is cleared and we reach the normal
    # path (which then fails for a different reason -- no stored session --
    # NOT the gate). Any error other than the gate's "disabled" is fine.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_ENABLE_SESSION_PROVIDERS", "1")
    try:
        get_session_client("claude-session")
    except RuntimeError as e:
        assert "disabled" not in str(e)
    except Exception:
        pass  # downstream (missing session/creds) -- gate was cleared


def test_stringy_false_does_not_enable(tmp_path, monkeypatch):
    # bool("false") is True in Python, but the gate parses explicitly.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_ENABLE_SESSION_PROVIDERS", "false")
    with pytest.raises(RuntimeError, match="disabled"):
        get_session_client("claude-session")
