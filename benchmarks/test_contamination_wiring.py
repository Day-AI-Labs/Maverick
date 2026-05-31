"""#320: the contamination guard now actually fires + is visible.

Covers:
  - load_leaked_briefs_from_file populates the (otherwise-empty) corpus
    from a persistent source, so the brief-in-corpus check can fire.
  - swe_bench._contamination_summary runs the guard and returns flag
    kinds; clean runs return "".
  - Row.contamination is a real CSV column (write_csv keeps it; only
    `extra` is dropped).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load(mod_name: str, rel: str):
    p = Path(__file__).parent / rel
    spec = importlib.util.spec_from_file_location(mod_name, p)
    mod = importlib.util.module_from_spec(spec)
    # dataclass string-annotation resolution needs the module in sys.modules
    # before exec_module runs the @dataclass decorator (see swe_bench fixture).
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def contam():
    return _load("contam_320", "_common/contamination_guard.py")


@pytest.fixture
def swebench():
    return _load("benchmarks_swe_bench", "swe_bench.py")


# ---------- leaked-brief file source ----------

def test_load_leaked_briefs_raw_lines(contam, tmp_path):
    f = tmp_path / "leaked.txt"
    f.write_text(
        "# confirmed-leaked SWE-bench briefs\n"
        "this brief leaked into training\n"
        "\n"
        "another leaked brief\n",
        encoding="utf-8",
    )
    n = contam.load_leaked_briefs_from_file(str(f))
    assert n == 2
    flags = contam.check(
        task_id="t", brief="this brief leaked into training",
        predicted_patch="x", model_id="claude-sonnet-4-6",
    )
    assert any(fl.kind == "brief_in_leaked_corpus" for fl in flags)


def test_load_leaked_briefs_precomputed_hash(contam):
    import hashlib
    brief = "precomputed-hash brief"
    h = hashlib.sha256(brief.strip().encode("utf-8")).hexdigest()[:16]
    # Feed the 16-char hash directly (community lists often ship hashes,
    # not raw briefs).
    contam._KNOWN_LEAKED_BRIEFS.clear()
    contam.add_known_leaked_brief("seed")  # exercise coexistence
    import os
    import tempfile
    fd, path = tempfile.mkstemp()
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(h + "\n")
        added = contam.load_leaked_briefs_from_file(path)
    finally:
        os.unlink(path)
    assert added == 1
    flags = contam.check(task_id="t", brief=brief, predicted_patch="x")
    assert any(fl.kind == "brief_in_leaked_corpus" for fl in flags)


def test_load_leaked_briefs_missing_file_is_noop(contam):
    assert contam.load_leaked_briefs_from_file("/no/such/file.txt") == 0


# ---------- swe_bench contamination wiring ----------

def test_contamination_summary_flags_verbatim_gold(swebench):
    gold = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"
    summary = swebench._contamination_summary(
        instance_id="i1", brief="fix the bug",
        predicted_patch=gold, gold_patch=gold,
        model_id="claude-opus-4-7",
    )
    assert "verbatim_gold_patch" in summary


def test_contamination_summary_clean_is_empty(swebench):
    summary = swebench._contamination_summary(
        instance_id="i1", brief="fix the bug",
        predicted_patch="--- a/y\n+++ b/y\n@@ -1 +1 @@\n-a\n+b\n",
        gold_patch="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n",
        model_id="claude-sonnet-4-6",
    )
    assert summary == ""


def test_contamination_summary_cutoff_after_publication(swebench):
    summary = swebench._contamination_summary(
        instance_id="i1", brief="fix it", predicted_patch="patch",
        gold_patch="", model_id="grok-4.3",  # cutoff 2026-03-01
        publication_date="2025-08-01",
    )
    assert "post_publication_cutoff" in summary


def test_contamination_is_a_csv_column(swebench, tmp_path):
    """The flag must surface in RESULTS_SWE.csv (extra is dropped, this isn't)."""
    Row = swebench.Row
    rows = [Row(
        instance_id="i1", pipeline="maverick", model_id="m",
        predicted_patch="p", outcome="success",
        contamination="verbatim_gold_patch",
    )]
    out = tmp_path / "RESULTS_SWE.csv"
    swebench.write_csv(rows, out)
    text = out.read_text()
    header = text.splitlines()[0]
    assert "contamination" in header
    assert "extra" not in header
    assert "verbatim_gold_patch" in text
