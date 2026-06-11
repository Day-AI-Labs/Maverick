"""Tests for the memory-leak quarantine watchdog. Deterministic — the test is
the sampler."""
from __future__ import annotations

import pytest
from maverick.leak_quarantine import LeakVerdict, LeakWatchdog, process_rss_bytes

MB = 1024 * 1024


def test_sustained_monotonic_growth_quarantines():
    fired: list[LeakVerdict] = []
    w = LeakWatchdog(threshold_bytes=10 * MB, consecutive=3, on_quarantine=fired.append)
    assert w.record("coder", 100 * MB) is False
    assert w.record("coder", 106 * MB) is False
    assert w.record("coder", 112 * MB) is True  # +12MB over 3 increasing samples
    assert w.is_quarantined("coder")
    assert fired and fired[0].component == "coder" and fired[0].growth_bytes == 12 * MB


def test_sawtooth_never_trips():
    w = LeakWatchdog(threshold_bytes=1 * MB, consecutive=3)
    # grow, GC-shrink, grow, GC-shrink — normal behavior
    for size in (100, 110, 95, 108, 96, 109):
        assert w.record("agent", size * MB) is False
    assert not w.is_quarantined("agent")


def test_growth_below_threshold_never_trips():
    w = LeakWatchdog(threshold_bytes=50 * MB, consecutive=3)
    for size in (100, 101, 102, 103, 104):
        assert w.record("agent", size * MB) is False


def test_quarantine_is_sticky_and_releasable():
    w = LeakWatchdog(threshold_bytes=1 * MB, consecutive=3)
    for size in (1, 3, 5):
        w.record("leaky", size * MB)
    assert w.is_quarantined("leaky")
    # Sticky: later shrinking samples don't lift it.
    assert w.record("leaky", 1 * MB) is True
    assert w.release("leaky") is True
    assert not w.is_quarantined("leaky")
    assert w.release("leaky") is False  # already lifted


def test_components_are_independent():
    w = LeakWatchdog(threshold_bytes=1 * MB, consecutive=3)
    for size in (1, 3, 5):
        w.record("leaky", size * MB)
        w.record("healthy", 2 * MB)
    assert w.is_quarantined("leaky") and not w.is_quarantined("healthy")
    assert [v.component for v in w.quarantined()] == ["leaky"]


def test_callback_failure_does_not_break_sampling():
    def _boom(v):
        raise RuntimeError("observer crashed")

    w = LeakWatchdog(threshold_bytes=1 * MB, consecutive=3, on_quarantine=_boom)
    for size in (1, 3, 5):
        w.record("x", size * MB)  # must not raise
    assert w.is_quarantined("x")


def test_validation_and_rss_helper():
    with pytest.raises(ValueError):
        LeakWatchdog(threshold_bytes=0)
    with pytest.raises(ValueError):
        LeakWatchdog(consecutive=2)
    assert process_rss_bytes() >= 0
