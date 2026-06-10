from __future__ import annotations

import random

import pytest
from maverick_evolve import EvalCase, evolve_live, make_agent_factory
from maverick_evolve.agent_adapter import (
    env_for,
    overlay_for,
    subprocess_run_one,
    write_overlay,
)


def test_env_for_maps_import_time_knobs():
    env = env_for({"max_swarm_fanout": 12, "verifier_confidence": 0.8})
    assert env["MAVERICK_MAX_SWARM_FANOUT"] == "12"
    assert env["MAVERICK_VERIFIER_CONFIDENCE"] == "0.8"


def test_overlay_for_enables_features():
    ov = overlay_for({
        "adaptive_compute.low_uncertainty": 0.3,
        "search.n": 4,
        "autonomy.disagreement_high": 0.6,
    })
    assert ov["adaptive_compute"] == {"enable": True, "low_uncertainty": 0.3}
    assert ov["search"] == {"enable": True, "n": 4}
    assert ov["autonomy"]["enable"] is True


def test_render_overlay_is_valid_toml(tmp_path):
    try:
        import tomllib  # 3.11+
    except ModuleNotFoundError:  # 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    cfg = {"search.n": 3, "adaptive_compute.low_uncertainty": 0.25}
    p = write_overlay(cfg, tmp_path / "config.toml")
    parsed = tomllib.loads(p.read_text())
    assert parsed["search"]["n"] == 3
    assert parsed["adaptive_compute"]["enable"] is True


def test_unknown_knobs_ignored():
    assert env_for({"mystery": 1}) == {}
    assert overlay_for({"mystery": 1}) == {}


def test_subprocess_run_one_uses_overlay_without_replacing_operator_config(monkeypatch, tmp_path):
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["env"] = kwargs["env"]
        seen["cwd"] = kwargs["cwd"]

        class Proc:
            stdout = "ok"

        return Proc()

    operator_config = tmp_path / "operator.toml"
    operator_config.write_text('[sandbox]\nbackend = "docker"\n', encoding="utf-8")
    monkeypatch.setenv("MAVERICK_CONFIG", str(operator_config))
    monkeypatch.setattr("maverick_evolve.agent_adapter.subprocess.run", fake_run)

    out = subprocess_run_one(
        "hello", {"search.n": 5, "max_swarm_fanout": 3}, workdir=str(tmp_path), python="py"
    )

    assert out == "ok"
    assert seen["args"] == ["py", "-m", "maverick.cli", "start", "hello"]
    assert seen["cwd"] == str(tmp_path)
    assert seen["env"]["MAVERICK_CONFIG"] == str(operator_config)
    assert seen["env"]["MAVERICK_CONFIG_OVERLAY"] != str(operator_config)
    assert seen["env"]["MAVERICK_MAX_SWARM_FANOUT"] == "3"


@pytest.mark.asyncio
async def test_full_wiring_with_fake_run_one(monkeypatch):
    """The end-to-end proof: a fake run_one that reads a config knob drives the
    real factory -> eval harness -> continuous-evolution loop, and it climbs.
    This is the same wiring the live subprocess runner uses."""
    monkeypatch.setattr("maverick_evolve.loop.calibration_frozen", lambda: False)

    async def fake_run_one(prompt: str, config: dict) -> str:
        # The "agent" is better when the fanout knob is higher; the eval case's
        # threshold comes from the prompt (graded landscape).
        return "GOOD" if config.get("max_swarm_fanout", 0) >= int(prompt) else "BAD"

    cases = [EvalCase(prompt=str(t), check=lambda o: o == "GOOD")
             for t in (2, 4, 6, 8, 10, 12, 14)]
    space = {"max_swarm_fanout": ("int", 1, 16)}
    best, history = await evolve_live(
        {"max_swarm_fanout": 4}, cases,
        run_one=fake_run_one,
        rounds=3, generations_per_round=40, space=space, rng=random.Random(0),
    )
    assert best.config["max_swarm_fanout"] >= 12
    assert best.score >= 6 / 7 - 1e-9


@pytest.mark.asyncio
async def test_make_agent_factory_produces_runnable_agent():
    async def fake_run_one(prompt, config):
        return f"answer for {prompt} with n={config.get('n')}"

    factory = make_agent_factory(fake_run_one)
    agent = factory({"n": 7})
    out = await agent("hello")
    assert out == "answer for hello with n=7"


def test_cli_load_cases(tmp_path):
    import json

    from maverick_evolve.cli import _load_cases
    p = tmp_path / "cases.json"
    p.write_text(json.dumps([
        {"prompt": "capital of France?", "reference": "Paris"},
        {"prompt": "no-ref still loads"},
        {"not_a_prompt": 1},  # skipped
    ]))
    cases = _load_cases(str(p))
    assert len(cases) == 2
    assert cases[0].reference == "Paris"


def test_cli_live_requires_cases(capsys):
    from maverick_evolve.cli import main
    rc = main(["--live"])
    assert rc == 2
    assert "requires --cases" in capsys.readouterr().out
