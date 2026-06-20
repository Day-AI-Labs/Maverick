"""Wiring of previously-orphaned capabilities into live chokepoints."""
from __future__ import annotations

import pytest

# ---- energy-aware routing wired into model_for_role -------------------------

def test_cheaper_model_tiers():
    from maverick.llm import MODEL_HAIKU, MODEL_OPUS, MODEL_SONNET, _cheaper_model
    assert _cheaper_model(MODEL_OPUS) == MODEL_SONNET
    assert _cheaper_model(MODEL_SONNET) == MODEL_HAIKU
    assert _cheaper_model(MODEL_HAIKU) == MODEL_HAIKU  # no lower tier


def test_model_for_role_downgrades_on_low_battery(monkeypatch):
    import maverick.energy_aware_router as ear
    import maverick.llm as llm
    # Force energy-aware ON + a low-battery reading.
    monkeypatch.setattr(ear, "enabled", lambda: True)
    monkeypatch.setattr(ear, "battery_state",
                        lambda: ear.BatteryState(on_battery=True, percent=10))
    # No config/override pinned -> default path -> orchestrator is Opus -> Sonnet.
    monkeypatch.setattr(llm, "get_role_model", lambda role: None, raising=False)
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", dict)
    monkeypatch.delenv("MAVERICK_MODEL_OVERRIDE", raising=False)
    monkeypatch.delenv("MAVERICK_MODEL_OVERRIDE_ORCHESTRATOR", raising=False)
    assert llm.model_for_role("orchestrator") == llm.MODEL_SONNET


def test_model_for_role_no_downgrade_on_wall_power(monkeypatch):
    import maverick.energy_aware_router as ear
    import maverick.llm as llm
    monkeypatch.setattr(ear, "enabled", lambda: True)
    monkeypatch.setattr(ear, "battery_state",
                        lambda: ear.BatteryState(on_battery=False, percent=100))
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", dict)
    monkeypatch.delenv("MAVERICK_MODEL_OVERRIDE", raising=False)
    assert llm.model_for_role("orchestrator") == llm.MODEL_OPUS


# ---- rate-limit predictor + circuit breaker fed from dispatch helpers --------

def test_record_provider_call_feeds_predictor():
    from maverick import rate_limit_predictor as rlp
    from maverick.llm import _record_provider_call
    rlp.reset()
    _record_provider_call("anthropic")
    _record_provider_call("anthropic")
    rows = {r["provider"]: r["recorded"] for r in rlp.report()}
    assert rows.get("anthropic") == 2


def test_feed_circuit_trips_breaker_on_failures():
    from maverick import circuit_breaker as cb
    from maverick.llm import _feed_circuit
    cb.reset_all()
    for _ in range(10):  # well past the default threshold
        _feed_circuit("flaky-provider", error=True)
    states = {s["key"]: s["state"] for s in cb.snapshot()}
    assert states.get("llm:flaky-provider") == "open"


def test_feed_circuit_success_keeps_closed():
    from maverick import circuit_breaker as cb
    from maverick.llm import _feed_circuit
    cb.reset_all()
    _feed_circuit("good-provider", error=False)
    states = {s["key"]: s["state"] for s in cb.snapshot()}
    assert states.get("llm:good-provider") == "closed"


# ---- diag CLI surfaces the read-only utilities ------------------------------

def test_diag_cli_group_registered():
    from maverick.cli import main
    names = main.commands["diag"].commands
    assert {"circuits", "ratelimits", "health", "cost-by-tag"} <= set(names)


# ---- approval delegation reachable from the consent path --------------------

def test_approval_delegation_route_importable_and_noop_without_rules():
    from maverick.approval_delegation import route
    # No rules configured -> None (default queue), so consent wiring is a no-op.
    assert route({"risk": "high", "tool": "shell"}, rules=[]) is None


# ---- queue dispatcher install reachable -------------------------------------

def test_queue_install_noop_without_backend(monkeypatch):
    import maverick.config as cfg
    import maverick.queue_dispatcher as qd
    import maverick.runner as runner
    monkeypatch.setattr(cfg, "load_config", dict)
    original = runner.get_dispatcher()
    try:
        assert qd.install_from_config() is False
        assert runner.get_dispatcher() is original
    finally:
        runner.set_dispatcher(original)


# ---- local skill distillation reachable -------------------------------------

def test_replay_trace_wired_into_blackboard(tmp_path):
    from maverick.blackboard import Blackboard
    from maverick.replay.trace import TraceWriter, read_trace
    bb = Blackboard()
    # Default: no trace writer -> posts don't crash and nothing is written.
    bb.post("a", "plan", "x")
    # Attach a writer -> every post is mirrored to the JSONL trace.
    path = tmp_path / "g.jsonl"
    bb.attach_trace(TraceWriter(path))
    bb.post("orchestrator", "plan", "do the thing")
    bb.post("coder", "tool", "ran tests")
    events = read_trace(path)
    assert [e["kind"] for e in events] == ["plan", "tool"]
    assert events[0]["agent"] == "orchestrator"


@pytest.mark.parametrize("enabled", [False, True])
def test_skill_distillation_local_gate(monkeypatch, enabled):
    import maverick.skill_distillation_local as sdl
    monkeypatch.setattr(sdl, "_env_true", lambda name: enabled)
    monkeypatch.setattr(sdl, "load_config", dict, raising=False)
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config",
                        lambda: {"self_learning": {"distill_local": enabled}})
    monkeypatch.delenv("MAVERICK_DISTILL_LOCAL", raising=False)
    assert sdl.enabled() is enabled
