"""budget_from_config() wires the [budget] section that was dead before.

config.get_budget_overrides() existed but was never called, so the
[budget] section of config.toml had no effect on any run. budget_from_config
is the single funnel; precedence is defaults < [budget] config < explicit
override, with None treated as "unset" and malformed config skipped.
"""
import pytest
from maverick.budget import Budget, budget_from_config


@pytest.fixture
def set_budget_cfg(monkeypatch):
    def _set(cfg: dict):
        monkeypatch.setattr("maverick.config.get_budget_overrides", lambda: cfg)
    return _set


def test_no_config_uses_budget_defaults(set_budget_cfg):
    set_budget_cfg({})
    b = budget_from_config()
    assert b.max_dollars == Budget().max_dollars  # 5.0
    assert b.max_wall_seconds == Budget().max_wall_seconds


def test_config_applies(set_budget_cfg):
    set_budget_cfg({"max_dollars": 1.5, "max_tool_calls": 42})
    b = budget_from_config()
    assert b.max_dollars == pytest.approx(1.5)
    assert b.max_tool_calls == 42


def test_explicit_override_beats_config(set_budget_cfg):
    set_budget_cfg({"max_dollars": 1.5})
    assert budget_from_config(max_dollars=9.0).max_dollars == pytest.approx(9.0)


def test_none_override_is_unset(set_budget_cfg):
    set_budget_cfg({"max_dollars": 1.5})
    # Passing through an unset optional flag must not clobber config.
    assert budget_from_config(max_dollars=None).max_dollars == pytest.approx(1.5)


def test_config_beats_caller_defaults(set_budget_cfg):
    set_budget_cfg({"max_dollars": 1.5})
    b = budget_from_config(defaults={"max_dollars": 2.0, "max_wall_seconds": 1800.0})
    assert b.max_dollars == pytest.approx(1.5)        # config wins over defaults
    assert b.max_wall_seconds == pytest.approx(1800.0)  # defaults fill the gap


def test_defaults_used_when_no_config(set_budget_cfg):
    set_budget_cfg({})
    b = budget_from_config(defaults={"max_dollars": 2.0})
    assert b.max_dollars == pytest.approx(2.0)


def test_malformed_config_value_is_skipped(set_budget_cfg):
    set_budget_cfg({"max_dollars": "not-a-number"})
    b = budget_from_config(defaults={"max_dollars": 2.0})
    assert b.max_dollars == pytest.approx(2.0)  # fell back, did not crash


# ---- MAVERICK_BUDGET_DOLLARS env override (the cookbooks' documented knob) ----

def test_env_budget_dollars_applies_over_config(set_budget_cfg, monkeypatch):
    set_budget_cfg({"max_dollars": 5.0})
    monkeypatch.setenv("MAVERICK_BUDGET_DOLLARS", "0.5")
    assert budget_from_config().max_dollars == pytest.approx(0.5)


def test_explicit_override_beats_env(set_budget_cfg, monkeypatch):
    set_budget_cfg({})
    monkeypatch.setenv("MAVERICK_BUDGET_DOLLARS", "0.5")
    # An explicit --max-dollars flag is more specific than the env var.
    assert budget_from_config(max_dollars=3.0).max_dollars == pytest.approx(3.0)


def test_malformed_env_budget_dollars_is_skipped(set_budget_cfg, monkeypatch):
    set_budget_cfg({"max_dollars": 1.5})
    monkeypatch.setenv("MAVERICK_BUDGET_DOLLARS", "not-a-number")
    assert budget_from_config().max_dollars == pytest.approx(1.5)  # kept config


def test_nonfinite_env_budget_dollars_is_skipped(set_budget_cfg, monkeypatch):
    set_budget_cfg({"max_dollars": 1.5})
    monkeypatch.setenv("MAVERICK_BUDGET_DOLLARS", "inf")
    # A non-finite cap would disable the cap; keep the prior layer instead.
    assert budget_from_config().max_dollars == pytest.approx(1.5)


def test_empty_env_budget_dollars_ignored(set_budget_cfg, monkeypatch):
    set_budget_cfg({"max_dollars": 1.5})
    monkeypatch.setenv("MAVERICK_BUDGET_DOLLARS", "")
    assert budget_from_config().max_dollars == pytest.approx(1.5)
