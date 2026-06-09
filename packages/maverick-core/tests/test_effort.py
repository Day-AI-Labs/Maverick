"""Per-role reasoning effort (output_config.effort) — the cost/latency lever."""
from __future__ import annotations

import pytest
from maverick import effort
from maverick.effort import effort_for_role, effort_supported

OPUS = "claude-opus-4-8"
SONNET = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5"
SONNET45 = "claude-sonnet-4-5"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("MAVERICK_EFFORT"):
            monkeypatch.delenv(k, raising=False)
    # Default: no config, feature off.
    monkeypatch.setattr(effort, "_config_effort", lambda: {})


# ---- model gating ----------------------------------------------------------

def test_effort_supported_matrix():
    assert effort_supported(OPUS) is True
    assert effort_supported(SONNET) is True
    assert effort_supported(HAIKU) is False     # haiku 4.5 rejects effort
    assert effort_supported(SONNET45) is False  # sonnet 4.5 rejects effort


def test_off_by_default():
    # Nothing configured -> None (omit effort, API default applies).
    assert effort_for_role("orchestrator", OPUS) is None
    assert effort_for_role("researcher", SONNET) is None


# ---- enabling via config ---------------------------------------------------

def test_enabled_applies_builtin_profile(monkeypatch):
    monkeypatch.setattr(effort, "_config_effort", lambda: {"enabled": True})
    # Critical roles stay high; bulk roles drop.
    assert effort_for_role("orchestrator", OPUS) == "high"
    assert effort_for_role("coder", SONNET) == "high"
    assert effort_for_role("researcher", SONNET) == "medium"
    assert effort_for_role("reflector", OPUS) == "low"
    # Unknown role -> no default -> None.
    assert effort_for_role("mystery", OPUS) is None


def test_enabled_but_unsupported_model_returns_none(monkeypatch):
    monkeypatch.setattr(effort, "_config_effort", lambda: {"enabled": True})
    assert effort_for_role("orchestrator", HAIKU) is None
    assert effort_for_role("researcher", SONNET45) is None


# ---- precedence ------------------------------------------------------------

def test_per_role_env_wins(monkeypatch):
    monkeypatch.setenv("MAVERICK_EFFORT_ORCHESTRATOR", "low")
    monkeypatch.setenv("MAVERICK_EFFORT", "max")
    assert effort_for_role("orchestrator", OPUS) == "low"


def test_global_env_applies_to_all_roles(monkeypatch):
    monkeypatch.setenv("MAVERICK_EFFORT", "medium")
    assert effort_for_role("orchestrator", OPUS) == "medium"
    assert effort_for_role("coder", SONNET) == "medium"


def test_config_per_role_and_default(monkeypatch):
    monkeypatch.setattr(effort, "_config_effort",
                        lambda: {"orchestrator": "max", "default": "low"})
    assert effort_for_role("orchestrator", OPUS) == "max"
    assert effort_for_role("coder", OPUS) == "low"  # falls to default


# ---- clamping (never 400) --------------------------------------------------

def test_xhigh_clamped_off_opus_78(monkeypatch):
    monkeypatch.setenv("MAVERICK_EFFORT", "xhigh")
    assert effort_for_role("coder", OPUS) == "xhigh"      # opus 4.8 supports it
    assert effort_for_role("coder", SONNET) == "high"     # sonnet -> clamp down


def test_max_clamped_off_opus_tier(monkeypatch):
    monkeypatch.setenv("MAVERICK_EFFORT", "max")
    assert effort_for_role("coder", OPUS) == "max"        # opus 4.8 supports max
    assert effort_for_role("coder", SONNET) == "high"     # sonnet -> clamp down


def test_invalid_level_is_ignored(monkeypatch):
    monkeypatch.setenv("MAVERICK_EFFORT", "turbo")
    assert effort_for_role("orchestrator", OPUS) is None


# ---- provider request shaping ----------------------------------------------

def test_effort_lands_in_anthropic_output_config(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    from maverick.providers.anthropic_provider import AnthropicClient
    p = AnthropicClient()
    msgs = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    # Supported model -> effort threads into output_config.
    kw = p._build_request("sys", msgs, None, 4096, None, OPUS, "medium")
    assert kw["output_config"]["effort"] == "medium"
    # No effort -> no output_config key (unchanged request).
    assert p._build_request("sys", msgs, None, 4096, None, OPUS, None).get("output_config") is None
    # Unsupported model -> effort is dropped defensively (never 400).
    assert p._build_request("sys", msgs, None, 4096, None, HAIKU, "medium").get("output_config") is None
