"""Benchmark manifest + cost-tracker + contamination-guard smoke tests."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def manifests():
    return _load_module(
        "benchmarks_manifests",
        Path(__file__).parent / "_common" / "manifests.py",
    )


@pytest.fixture
def cost_tracker_mod():
    return _load_module(
        "benchmarks_cost_tracker",
        Path(__file__).parent / "_common" / "cost_tracker.py",
    )


@pytest.fixture
def contam_mod():
    return _load_module(
        "benchmarks_contam",
        Path(__file__).parent / "_common" / "contamination_guard.py",
    )


class TestManifests:
    def test_headline_set_includes_three_wedge_benchmarks(self, manifests):
        headline = manifests.headline_benchmarks()
        assert "swebench_pro" in headline
        assert "gaia_l3" in headline
        assert "osworld_verified" in headline

    def test_swebench_verified_not_headline(self, manifests):
        """Contaminated per Feb 2026 OpenAI audit; explicitly not headline."""
        # We don't include SWE-bench Verified at all -- the manifest is
        # SWE-bench Pro, the successor.
        assert "swebench_verified" not in manifests.all_benchmarks()
        assert "swebench_pro" in manifests.all_benchmarks()

    def test_thresholds_are_ordered(self, manifests):
        """Every benchmark's SOTA threshold must be > the competitive one."""
        for name in manifests.all_benchmarks():
            m = manifests.get(name)
            assert m.threshold_sota > m.threshold_competitive, (
                f"{name}: SOTA {m.threshold_sota} <= competitive "
                f"{m.threshold_competitive}"
            )

    def test_unknown_benchmark_raises(self, manifests):
        with pytest.raises(KeyError):
            manifests.get("nonsense_bench")


class TestCostTracker:
    def test_writes_row_on_exit(self, cost_tracker_mod, tmp_path):
        out = tmp_path / "r.jsonl"
        from maverick.budget import Budget
        with cost_tracker_mod.cost_tracker(
            "task-1", "maverick", results_path=out,
        ) as t:
            b = Budget(max_dollars=10.0)
            b.dollars = 1.23
            b.input_tokens = 1000
            b.output_tokens = 500
            t.absorb_budget(b)
            t.row.success = True
        rows = cost_tracker_mod.load_results(out)
        assert len(rows) == 1
        assert rows[0].task_id == "task-1"
        assert rows[0].cost_usd == 1.23
        assert rows[0].tokens_in == 1000
        assert rows[0].success is True
        assert rows[0].latency_s >= 0

    def test_pareto_frontier_per_pipeline(self, cost_tracker_mod):
        from benchmarks_cost_tracker import TaskRow
        rows = [
            TaskRow(task_id="t1", pipeline="maverick", success=True, cost_usd=2.0),
            TaskRow(task_id="t2", pipeline="maverick", success=False, cost_usd=1.5),
            TaskRow(task_id="t1", pipeline="sonnet_single", success=False, cost_usd=0.1),
            TaskRow(task_id="t2", pipeline="sonnet_single", success=False, cost_usd=0.1),
        ]
        front = cost_tracker_mod.pareto_frontier(rows)
        # maverick: 0.5 success, $3.50; sonnet_single: 0.0 success, $0.20.
        d = {p: (c, r) for p, c, r in front}
        assert d["maverick"] == (3.5, 0.5)
        assert d["sonnet_single"] == (pytest.approx(0.2), 0.0)


class TestContaminationGuard:
    def test_verbatim_gold_patch_flagged(self, contam_mod):
        gold = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"
        flags = contam_mod.check(
            task_id="t1", brief="fix it",
            predicted_patch=gold, gold_patch=gold,
            model_id="claude-opus-4-7",
        )
        assert any(f.kind == "verbatim_gold_patch" for f in flags)

    def test_clean_run_no_flags(self, contam_mod):
        flags = contam_mod.check(
            task_id="t1", brief="fix it",
            predicted_patch="--- a/y\n+++ b/y\n@@ -1 +1 @@\n-x\n+z\n",
            gold_patch="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n",
            model_id="claude-sonnet-4-6",
        )
        assert flags == []

    def test_cutoff_after_publication_flagged(self, contam_mod):
        """A model trained AFTER the benchmark was published may have
        seen the gold answers."""
        flags = contam_mod.check(
            task_id="t1", brief="fix it",
            predicted_patch="patch",
            model_id="grok-4.3",  # cutoff 2026-03-01
            benchmark_publication_date="2025-08-01",
        )
        assert any(f.kind == "post_publication_cutoff" for f in flags)

    def test_known_leaked_brief_flagged(self, contam_mod):
        brief = "this brief is on the leaked list"
        contam_mod.add_known_leaked_brief(brief)
        flags = contam_mod.check(
            task_id="t1", brief=brief,
            predicted_patch="x", model_id="claude-opus-4-7",
        )
        assert any(f.kind == "brief_in_leaked_corpus" for f in flags)
