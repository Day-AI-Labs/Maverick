"""Energy/CO2 accounting: coefficient arithmetic, config/env overrides, the
world-model adapter, the always-rendered disclaimer, and the zero case.
Fully offline."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from maverick import energy_accounting as ea


@pytest.fixture
def defaults(monkeypatch):
    """Pin the documented defaults: no env overrides, empty config."""
    monkeypatch.delenv("MAVERICK_ENERGY_WH_PER_1K_TOKENS", raising=False)
    monkeypatch.delenv("MAVERICK_ENERGY_GRID_CO2_G_PER_KWH", raising=False)
    import maverick.config as config_mod
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: {})


def test_arithmetic_with_documented_defaults(defaults):
    est = ea.estimate(1000, 1000)
    # weighted: (1000 + 3*1000)/1000 = 4 ktok; 4 * 0.3 Wh = 1.2 Wh
    assert est.wh == pytest.approx(4.0 * ea.WH_PER_1K_TOKENS_DEFAULT)
    # 1.2 Wh = 0.0012 kWh * 400 g/kWh = 0.48 g
    assert est.co2_g == pytest.approx(est.wh / 1000.0 * ea.GRID_CO2_G_PER_KWH_DEFAULT)


def test_output_tokens_weighted_3x(defaults):
    out_heavy = ea.estimate(0, 1000)
    in_heavy = ea.estimate(1000, 0)
    assert out_heavy.wh == pytest.approx(in_heavy.wh * ea.OUTPUT_TOKEN_WEIGHT)


def test_zero_usage_is_zero(defaults):
    est = ea.estimate(0, 0)
    assert est.wh == 0.0
    assert est.co2_g == 0.0
    assert ea.estimate_run([]).wh == 0.0


def test_config_override_and_env_wins(defaults, monkeypatch):
    import maverick.config as config_mod
    monkeypatch.setattr(
        config_mod, "load_config",
        lambda *a, **k: {"energy": {"wh_per_1k_tokens": 1.0, "grid_co2_g_per_kwh": 100}},
    )
    est = ea.estimate(1000, 0)
    assert est.wh == pytest.approx(1.0)
    assert est.co2_g == pytest.approx(0.1)
    # Env beats config.
    monkeypatch.setenv("MAVERICK_ENERGY_WH_PER_1K_TOKENS", "2.0")
    assert ea.estimate(1000, 0).wh == pytest.approx(2.0)


def test_bad_overrides_fall_back_to_defaults(defaults, monkeypatch):
    monkeypatch.setenv("MAVERICK_ENERGY_WH_PER_1K_TOKENS", "banana")
    monkeypatch.setenv("MAVERICK_ENERGY_GRID_CO2_G_PER_KWH", "-5")
    assert ea.wh_per_1k_tokens() == ea.WH_PER_1K_TOKENS_DEFAULT
    assert ea.grid_co2_g_per_kwh() == ea.GRID_CO2_G_PER_KWH_DEFAULT


def test_estimate_run_duck_typed_rows(defaults):
    rows = [
        SimpleNamespace(input_tokens=500, output_tokens=100),  # EpisodeSpend shape
        {"input_tokens": 300, "output_tokens": 50},
        {"in_tokens": 200, "out_tokens": 50},                  # alt key names
    ]
    est = ea.estimate_run(rows)
    assert est.wh == pytest.approx(ea.estimate(1000, 200).wh)


def test_gather_from_world(defaults):
    episodes = [
        SimpleNamespace(input_tokens=1000, output_tokens=200),
        SimpleNamespace(input_tokens=500, output_tokens=100),
    ]
    seen = {}

    class FakeWorld:
        def list_episodes(self, limit=50):
            seen["limit"] = limit
            return episodes

    rows = ea.gather_from_world(FakeWorld(), limit=9)
    assert seen["limit"] == 9
    est = ea.estimate_run(rows)
    assert est.wh == pytest.approx(ea.estimate(1500, 300).wh)


def test_disclaimer_always_rendered(defaults):
    assert ea.DISCLAIMER in ea.render(ea.estimate(5000, 1000))
    assert ea.DISCLAIMER in ea.render(ea.estimate(0, 0))  # even for zero usage
    out = ea.render(ea.estimate(1000, 1000))
    assert "ESTIMATE" in out
    assert "Wh" in out and "CO2" in out
