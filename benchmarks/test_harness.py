"""Harness smoke test.

Verifies the dry-run path works end-to-end without invoking the LLM, so
CI can prove the harness machinery itself isn't broken even when there
are no API credentials in the environment.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def harness():
    """Import the harness module by file path so this test works whether
    benchmarks/ is on PYTHONPATH or not."""
    import importlib.util
    p = Path(__file__).parent / "harness.py"
    spec = importlib.util.spec_from_file_location("benchmarks.harness", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dry_run_produces_row(harness, tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_BENCH_DRY_RUN", "1")
    bench = tmp_path / "fake.md"
    bench.write_text("dummy benchmark spec")

    row = harness.run_one(
        benchmark_path=bench,
        max_dollars=1.0,
        max_wall_seconds=10.0,
        tag="ci",
        db_path=tmp_path / "world.db",
    )

    assert row["agent"] == "maverick"
    assert row["outcome"] == "dry-run"
    assert row["wall_seconds"] >= 0
    assert row["cost_dollars"] == 0.0


def test_append_results_creates_table(harness, tmp_path):
    out = tmp_path / "RESULTS.md"
    row = {
        "benchmark": "x.md", "tag": "v0.1", "agent": "maverick",
        "wall_seconds": 0.5, "cost_dollars": 0.01,
        "input_tokens": 100, "output_tokens": 50, "tool_calls": 2,
        "outcome": "success",
    }
    harness.append_results(row, out)

    content = out.read_text()
    assert "Maverick benchmark results" in content
    assert "| benchmark |" in content
    assert "| x.md | v0.1 | maverick | auto | 0.5 |" in content


def test_append_is_idempotent_per_table_creation(harness, tmp_path):
    """Calling append_results twice doesn't duplicate the header."""
    out = tmp_path / "RESULTS.md"
    row1 = {
        "benchmark": "a.md", "tag": "v1", "agent": "maverick",
        "wall_seconds": 1, "cost_dollars": 0.1,
        "input_tokens": 10, "output_tokens": 5, "tool_calls": 1,
        "outcome": "success",
    }
    row2 = {**row1, "benchmark": "b.md"}
    harness.append_results(row1, out)
    harness.append_results(row2, out)
    content = out.read_text()
    assert content.count("| benchmark |") == 1
    assert "a.md" in content
    assert "b.md" in content


def test_append_results_marks_source_auto_vs_manual(harness, tmp_path):
    """Harness rows are source=auto; a hand-filled comparator row keeps its
    own source, so auto vs. manual is visible in the output (issue #320)."""
    out = tmp_path / "RESULTS.md"
    harness.append_results(
        {"benchmark": "x.md", "tag": "v1", "agent": "maverick",
         "wall_seconds": 1, "cost_dollars": 0.1, "input_tokens": 10,
         "output_tokens": 5, "tool_calls": 1, "outcome": "success"},
        out,
    )
    harness.append_results(
        {"benchmark": "x.md", "tag": "v1", "agent": "openclaw", "source": "manual",
         "wall_seconds": 2, "cost_dollars": 0.2, "input_tokens": 20,
         "output_tokens": 10, "tool_calls": 3, "outcome": "success"},
        out,
    )
    content = out.read_text()
    assert "| source |" in content            # new column present in header
    assert "| maverick | auto |" in content   # harness row -> auto
    assert "| openclaw | manual |" in content  # hand-filled comparator -> manual
