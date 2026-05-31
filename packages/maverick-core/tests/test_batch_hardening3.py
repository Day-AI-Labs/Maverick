"""Tests for the third batch of pre-launch hardening fixes."""
import pytest
from maverick.circuit_breaker import CircuitBreaker, CircuitOpen, CircuitState


def test_half_open_rejects_concurrent_probe():
    cb = CircuitBreaker("t")
    cb._state = CircuitState.HALF_OPEN
    cb._probe_in_flight = True  # a probe is already running
    with pytest.raises(CircuitOpen, match="in flight"):
        cb.call(lambda: "x")


def test_half_open_allows_one_probe_and_clears_flag():
    cb = CircuitBreaker("t")
    cb._state = CircuitState.HALF_OPEN
    assert cb.call(lambda: "ok") == "ok"
    assert cb._probe_in_flight is False  # cleared after the probe resolves


def test_half_open_clears_flag_on_failure():
    cb = CircuitBreaker("t")
    cb._state = CircuitState.HALF_OPEN
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cb._probe_in_flight is False


def test_replicate_rejects_traversal_model():
    from maverick.tools.replicate_tool import _op_run
    assert "invalid model" in _op_run({"model": "../predictions/x"})
    assert "invalid model" in _op_run({"model": "noslash"})


def test_home_assistant_safe_seg():
    from maverick.tools.home_assistant_tool import _safe_seg
    assert _safe_seg("light.living_room")
    assert not _safe_seg("../config")
    assert not _safe_seg("a/b")
    assert not _safe_seg("")
