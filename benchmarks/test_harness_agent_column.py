"""Harness agent column is parameterised (#320).

run_one() previously hard-coded agent="maverick", so a comparator system's
numbers could only be hand-edited into RESULTS.md. The agent label is now a
parameter / --agent flag, making a comparator run a first-class row.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def harness():
    p = Path(__file__).parent / "harness.py"
    spec = importlib.util.spec_from_file_location("benchmarks._harness_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_agent_is_maverick(harness, tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_BENCH_DRY_RUN", "1")
    bench = tmp_path / "b.md"
    bench.write_text("spec")
    row = harness.run_one(bench, 1.0, 10.0, "ci", db_path=tmp_path / "w.db")
    assert row["agent"] == "maverick"


def test_agent_label_is_parameterised(harness, tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_BENCH_DRY_RUN", "1")
    bench = tmp_path / "b.md"
    bench.write_text("spec")
    row = harness.run_one(
        bench, 1.0, 10.0, "ci", db_path=tmp_path / "w.db", agent="openclaw",
    )
    assert row["agent"] == "openclaw"


def test_agent_column_written_to_results(harness, tmp_path):
    results = tmp_path / "RESULTS.md"
    harness.append_results(
        {"benchmark": "b.md", "tag": "v1", "agent": "hermes",
         "wall_seconds": 1, "cost_dollars": 0.0, "input_tokens": 0,
         "output_tokens": 0, "tool_calls": 0, "outcome": "ok"},
        results,
    )
    body = results.read_text()
    assert "hermes" in body
