"""Smoke tests for the security benchmark scripts (collected by CI).

These keep the benchmark code itself honest and runnable -- they assert
structure and invariants, not specific accuracy numbers (those live in
RESULTS.md and will drift as the shield improves).
"""
from __future__ import annotations

from benchmarks.security import corpus, detector_score, latency_bench


def test_corpus_has_both_labels_and_all_splits():
    cases = corpus.load_all()
    assert {"train", "heldout", "benign"} <= {c.split for c in cases}
    assert any(c.label == "attack" for c in cases)
    assert any(c.label == "benign" for c in cases)
    assert len(cases) > 50


def test_detector_summary_actually_scores_the_corpus():
    s = detector_score.summary()
    assert set(s) == set(detector_score.BACKENDS)
    did = s["defense_in_depth"]
    # Sanity: the combined scorer fires on the train corpus it was tuned on.
    k, n, _ci = did["tpr_train"]
    assert n > 0 and k / n > 0.5
    # FPR is a well-formed proportion.
    fp, nb, _ = did["fpr_benign"]
    assert 0 <= fp <= nb


def test_leakage_guard_flags_a_train_phrase_only():
    train_text = next(c.text for c in corpus.load_all() if c.split == "train")
    flagged = detector_score.train_overlap([train_text, "a wholly novel benign sentence"])
    assert flagged == [train_text]


def test_evasion_sweep_covers_every_obfuscation():
    eva = detector_score.evasion(detector_score.BACKENDS["defense_in_depth"])
    assert set(eva) == set(corpus.obfuscations())
    assert all(0 <= k <= n for k, n in eva.values())


def test_latency_measure_runs_and_is_finite():
    res = latency_bench.measure(reps_small=1)
    assert set(res) == set(latency_bench.SCANNERS)
    for m in res.values():
        assert m["n"] >= 1
        assert 0.0 <= m["p50"] <= m["max"]
