"""Tests for 2027-H1 observability/UX tools: trace_compare, latency_heatmap,
tool_call_inspector. Deterministic and offline."""
from __future__ import annotations

from maverick.tools.latency_heatmap import latency_heatmap
from maverick.tools.tool_call_inspector import tool_call_inspector
from maverick.tools.trace_compare import trace_compare

# ---- trace_compare ----

def test_trace_identical_shape():
    t = trace_compare()
    a = [{"seq": 1, "t": 1.0, "kind": "tool", "name": "fs"}, {"seq": 2, "t": 2.0, "kind": "llm"}]
    b = [{"seq": 1, "t": 9.9, "kind": "tool", "name": "fs"}, {"seq": 2, "t": 8.8, "kind": "llm"}]
    out = t.fn({"a": a, "b": b})
    assert "matched: 2/2" in out and "identical shape" in out


def test_trace_field_divergence():
    t = trace_compare()
    a = [{"seq": 1, "kind": "tool", "name": "fs"}]
    b = [{"seq": 1, "kind": "tool", "name": "shell"}]
    out = t.fn({"a": a, "b": b})
    assert "diverge-at: 0" in out and "name: 'fs' != 'shell'" in out


def test_trace_kind_divergence_and_length():
    t = trace_compare()
    a = [{"kind": "tool"}, {"kind": "llm"}]
    b = [{"kind": "tool"}]
    out = t.fn({"a": a, "b": b})
    assert "diverge-at: 1" in out and "only in a" in out


def test_trace_validation():
    t = trace_compare()
    assert t.fn({"a": "x", "b": []}).startswith("ERROR")


# ---- latency_heatmap ----

def test_heatmap_bands_and_percentiles():
    t = latency_heatmap()
    samples = [{"tool": "fs", "ms": 5}, {"tool": "fs", "ms": 50}, {"tool": "fs", "ms": 5000}]
    out = t.fn({"samples": samples})
    assert "fs" in out and "<10ms" in out and "≥10s" in out
    assert "p50=" in out and "p95=" in out


def test_heatmap_multiple_tools_sorted():
    t = latency_heatmap()
    out = t.fn({"samples": [{"tool": "zebra", "ms": 1}, {"tool": "alpha", "ms": 1}]})
    lines = out.splitlines()
    # header then alpha before zebra (sorted)
    assert lines[1].startswith("alpha") and lines[2].startswith("zebra")


def test_heatmap_validation():
    t = latency_heatmap()
    assert t.fn({"samples": []}).startswith("ERROR")
    assert t.fn({"samples": [{"tool": "x", "ms": -1}]}).startswith("ERROR")
    assert t.fn({"samples": [{"tool": "x"}]}).startswith("ERROR")


# ---- tool_call_inspector ----

def test_inspector_counts_and_error_rate():
    t = tool_call_inspector()
    calls = [
        {"tool": "fs", "ms": 10},
        {"tool": "fs", "ms": 20, "error": "boom"},
        {"tool": "web", "ok": True, "ms": 100},
    ]
    out = t.fn({"calls": calls})
    assert "calls: 3  tools: 2  errors: 1 (33%)" in out
    assert "fs: n=2 err=1 (50%)" in out and "HIGH-ERROR" in out
    assert "'boom'" in out


def test_inspector_threshold_and_ok_default():
    t = tool_call_inspector()
    out = t.fn({"calls": [{"tool": "a"}, {"tool": "a", "error": "x"}], "error_threshold": 0.9})
    # 50% error rate, threshold 0.9 -> not flagged
    assert "HIGH-ERROR" not in out


def test_inspector_validation():
    t = tool_call_inspector()
    assert t.fn({"calls": []}).startswith("ERROR")
    assert t.fn({"calls": [{"ms": 1}]}).startswith("ERROR")
    assert t.fn({"calls": [{"tool": "a"}], "error_threshold": 2}).startswith("ERROR")


def test_batch_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        pass

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    for name in ("trace_compare", "latency_heatmap", "tool_call_inspector"):
        assert name in names
