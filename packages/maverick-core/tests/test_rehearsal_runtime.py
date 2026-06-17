"""Live rehearsal wiring: build a world-model from the captured Operating Record
and gate a tool on it -- proceeding on good history, holding on bad, and staying
fail-open when disabled or data-less.
"""
from __future__ import annotations

from maverick import rehearsal as rh
from maverick import rehearsal_runtime as rt
from maverick.trajectory_store import TrajectoryStep, TrajectoryStore


def _store(tmp_path, outcome):
    """A store where role=coder runs `shell` in domain=ops, then finishes with
    the given terminal outcome -- 6 episodes so support clears the floor."""
    store = TrajectoryStore(path=tmp_path / "t.ndjson")
    for e in range(6):
        store.record(TrajectoryStep(ts=1.0, goal_id=1, episode_id=e, step=0,
                                    role="coder", tool="shell", domain="ops"))
        store.record(TrajectoryStep(ts=1.0, goal_id=1, episode_id=e, step=1,
                                    role="coder", tool="", domain="ops", is_final=True,
                                    outcome=outcome))
    return store


def test_encode_state_is_general_to_specific():
    assert rt.encode_state("ops", "coder", "shell") == ("ops", "coder", "shell")
    assert rt.encode_state(None, None, None) == ("", "", "")


def test_gate_tool_fail_open_when_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("MAVERICK_REHEARSAL", raising=False)
    monkeypatch.setattr("maverick.rehearsal._settings", lambda: dict(rh._DEFAULTS))
    rt.reset_cache()
    v = rt.gate_tool(domain="ops", role="coder", last_tool="", tool_name="shell")
    assert v.decision == rh.PROCEED and "disabled" in v.reason


def test_gate_tool_fail_open_when_no_data(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_REHEARSAL", "1")
    monkeypatch.setattr("maverick.trajectory_store.shared",
                        lambda: TrajectoryStore(path=tmp_path / "empty.ndjson"))
    rt.reset_cache()
    v = rt.gate_tool(domain="ops", role="coder", last_tool="", tool_name="shell")
    assert v.decision == rh.PROCEED and "no world-model" in v.reason


def test_gate_tool_proceeds_on_good_history(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_REHEARSAL", "1")
    monkeypatch.setattr("maverick.trajectory_store.shared", lambda: _store(tmp_path, 0.9))
    rt.reset_cache()
    v = rt.gate_tool(domain="ops", role="coder", last_tool="", tool_name="shell")
    assert v.decision == rh.PROCEED and v.known
    assert v.predicted_outcome > 0.7


def test_gate_tool_holds_on_bad_history(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_REHEARSAL", "1")
    monkeypatch.setattr("maverick.trajectory_store.shared", lambda: _store(tmp_path, 0.05))
    rt.reset_cache()
    v = rt.gate_tool(domain="ops", role="coder", last_tool="", tool_name="shell")
    assert v.decision == rh.BLOCK and v.predicted_outcome < 0.3


def test_build_model_generalises_across_role(tmp_path, monkeypatch):
    # The backoff model lets a NEW role in a known domain still be vouched for
    # (generalises over the trailing feature) rather than escalating blindly.
    monkeypatch.setattr("maverick.trajectory_store.shared", lambda: _store(tmp_path, 0.9))
    rt.reset_cache()
    model = rt._model()
    assert model is not None
    # exact context known; novel last_tool within the same (domain, role) backs off
    assert model.support(("ops", "coder", "novel_prev"), "shell") >= 3

def test_model_cache_is_partitioned_by_trajectory_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_REHEARSAL", "1")
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)

    from maverick.paths import reset_tenant, set_tenant
    from maverick.trajectory_store import reset_shared, shared

    reset_shared()
    rt.reset_cache()

    token = set_tenant("tenant-a")
    try:
        store_a = shared()
        for e in range(6):
            store_a.record(TrajectoryStep(ts=1.0, goal_id=1, episode_id=e, step=0,
                                          role="coder", tool="shell", domain="ops"))
            store_a.record(TrajectoryStep(ts=1.0, goal_id=1, episode_id=e, step=1,
                                          role="coder", tool="", domain="ops",
                                          is_final=True, outcome=0.9))
        verdict_a = rt.gate_tool(domain="ops", role="coder", last_tool="", tool_name="shell")
    finally:
        reset_tenant(token)

    assert verdict_a.decision == rh.PROCEED and verdict_a.known

    token = set_tenant("tenant-b")
    try:
        store_b = shared()
        assert store_b.path != store_a.path
        assert store_b.count() == 0
        verdict_b = rt.gate_tool(domain="ops", role="coder", last_tool="", tool_name="shell")
    finally:
        reset_tenant(token)

    assert verdict_b.decision == rh.PROCEED
    assert not verdict_b.known
    assert "no world-model" in verdict_b.reason
