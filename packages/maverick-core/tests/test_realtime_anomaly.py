"""Real-time (online) anomaly detection: rolling z-score spike flagging."""
from __future__ import annotations

from maverick.realtime_anomaly import RollingAnomalyDetector, StreamMonitor


def test_warmup_never_flags():
    d = RollingAnomalyDetector(min_samples=10)
    for _ in range(9):
        assert d.update(100.0).is_anomaly is False  # below min_samples


def test_stable_then_spike():
    d = RollingAnomalyDetector(window=50, z_threshold=3.0, min_samples=10)
    for _ in range(30):
        r = d.update(10.0 + (_ % 3) * 0.1)  # small jitter so stdev > 0
        assert not r.is_anomaly
    spike = d.update(1000.0)
    assert spike.is_anomaly is True
    assert spike.z_score > 3.0


def test_normal_value_not_flagged_after_warmup():
    d = RollingAnomalyDetector(min_samples=10)
    for i in range(30):
        d.update(50.0 + (i % 5))
    assert d.update(52.0).is_anomaly is False


def test_flat_history_any_deviation_is_anomaly():
    d = RollingAnomalyDetector(min_samples=5)
    for _ in range(10):
        d.update(7.0)            # perfectly flat
    assert d.update(7.0).is_anomaly is False   # same value: fine
    assert d.update(7.5).is_anomaly is True    # any deviation flagged


def test_negative_spike_flagged():
    d = RollingAnomalyDetector(min_samples=10, z_threshold=3.0)
    for i in range(30):
        d.update(100.0 + (i % 4))
    assert d.update(0.0).is_anomaly is True   # a drop is anomalous too


def test_window_forgets_old_values():
    d = RollingAnomalyDetector(window=10, min_samples=5, z_threshold=3.0)
    for _ in range(10):
        d.update(1.0)
    for _ in range(10):
        d.update(1000.0)          # window now full of the new regime
    # the new regime is the baseline; another 1000 is normal now
    assert d.update(1000.0).is_anomaly is False


def test_stream_monitor_independent_streams():
    m = StreamMonitor(min_samples=5, z_threshold=3.0)
    for i in range(20):
        m.update("cost", 0.01 + (i % 3) * 0.001)     # low-variance baseline
        m.update("latency", 100.0 + (i % 5))          # jitter -> stdev > 0
    assert m.update("cost", 5.0).is_anomaly is True       # cost spike
    assert m.update("latency", 101.0).is_anomaly is False  # within normal range
    assert m.streams() == ["cost", "latency"]
