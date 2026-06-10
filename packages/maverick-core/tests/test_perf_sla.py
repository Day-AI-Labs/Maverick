"""Performance SLA harness: real measurements against published thresholds."""
from __future__ import annotations

from maverick import perf_sla


def test_thresholds_match_published_doc():
    # the doc and the code must agree on which rows are enforced here
    assert set(perf_sla.THRESHOLDS) == {
        "dispatch_overhead_p95_ms", "compaction_200msg_ms",
        "world_write_p95_ms", "world_read_p95_ms"}


def test_dispatch_overhead_within_sla():
    r = perf_sla.check_dispatch_overhead(n=50)
    assert r.passed, f"{r.measured}ms > {r.threshold}ms"


def test_compaction_latency_within_sla():
    r = perf_sla.check_compaction_latency()
    assert r.passed, f"{r.measured}ms > {r.threshold}ms"


def test_world_write_within_sla(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    r = perf_sla.check_world_write(n=50)
    assert r.passed, f"{r.measured}ms > {r.threshold}ms"


def test_world_read_within_sla(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    r = perf_sla.check_world_read(n=50)
    assert r.passed, f"{r.measured}ms > {r.threshold}ms"


def test_render_marks_breach():
    breach = perf_sla.SLAResult("x", measured=99.0, threshold=1.0)
    ok = perf_sla.SLAResult("y", measured=0.5, threshold=1.0)
    out = perf_sla.render([breach, ok])
    assert "BREACH" in out and "PASS" in out


def test_p95_math():
    samples = [1.0] * 95 + [100.0] * 5
    assert perf_sla._p95(samples) >= 1.0
    assert perf_sla._p95([2.0]) == 2.0
    assert perf_sla._p95([]) == 0.0
