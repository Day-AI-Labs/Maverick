"""Self-consistency (majority-vote) tie-break in best-of-N selection.

When no ground-truth tests score the candidates (all score 0.0 — the
common case for real coding tasks), select_best_candidate prefers the
patch whose changed-file set agrees with the plurality of other
attempts. Strict refinement: a no-op when every attempt touches a
distinct file set. Toggle with MAVERICK_BON_CONSENSUS=0.
"""
from __future__ import annotations

import pytest

from maverick.coding_mode import (
    Candidate,
    _changed_files_in_patch,
    select_best_candidate,
)


def _cand(index: int, files: list[str], extra: str = "") -> Candidate:
    body = "".join(
        f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1 +1 @@\n+line{extra}\n"
        for f in files
    )
    return Candidate(index=index, patch=body, score=0.0, apply_check_passed=True)


class TestChangedFilesParser:
    def test_parses_diff_git_headers(self):
        patch = "diff --git a/src/x.py b/src/x.py\n@@ -1 +1 @@\n+y\n"
        assert _changed_files_in_patch(patch) == frozenset({"src/x.py"})

    def test_parses_multiple_files(self):
        patch = (
            "diff --git a/a.py b/a.py\n+++ b/a.py\n"
            "diff --git a/b.py b/b.py\n+++ b/b.py\n"
        )
        assert _changed_files_in_patch(patch) == frozenset({"a.py", "b.py"})

    def test_empty_or_nondiff_is_empty(self):
        assert _changed_files_in_patch("") == frozenset()
        assert _changed_files_in_patch("just prose, no diff") == frozenset()

    def test_ignores_dev_null(self):
        patch = "+++ /dev/null\n"
        assert _changed_files_in_patch(patch) == frozenset()


class TestConsensusSelection:
    def test_plurality_file_set_wins_over_outlier(self):
        # Two attempts agree on {core.py}; a later, lone attempt touches
        # {other.py}. Without consensus the later attempt (index 2) would
        # win; consensus picks the agreeing pair.
        agree_a = _cand(0, ["core.py"], extra="a")
        agree_b = _cand(1, ["core.py"], extra="b")
        outlier = _cand(2, ["other.py"])
        best = select_best_candidate([agree_a, agree_b, outlier])
        assert best.index in (0, 1)
        assert _changed_files_in_patch(best.patch) == frozenset({"core.py"})

    def test_distinct_file_sets_reduce_to_index_order(self):
        # Every attempt touches a different file -> consensus all 0 ->
        # prior behavior (prefer last attempt) is preserved.
        c0 = _cand(0, ["a.py"])
        c1 = _cand(1, ["b.py"])
        c2 = _cand(2, ["c.py"])
        assert select_best_candidate([c0, c1, c2]).index == 2

    def test_toggle_off_restores_index_preference(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_BON_CONSENSUS", "0")
        agree_a = _cand(0, ["core.py"], extra="a")
        agree_b = _cand(1, ["core.py"], extra="b")
        outlier = _cand(2, ["other.py"])
        # With consensus disabled, the last attempt (index 2) wins again.
        assert select_best_candidate([agree_a, agree_b, outlier]).index == 2

    def test_nonzero_scores_ignore_consensus(self):
        # When ground-truth tests scored the candidates, the highest
        # score must win regardless of file-set agreement.
        loser_a = _cand(0, ["core.py"], extra="a")
        loser_b = _cand(1, ["core.py"], extra="b")
        winner = _cand(2, ["other.py"])
        winner.score = 1.0
        assert select_best_candidate([loser_a, loser_b, winner]).index == 2

    def test_selection_is_deterministic(self):
        cands = [
            _cand(0, ["core.py"], extra="a"),
            _cand(1, ["core.py"], extra="b"),
            _cand(2, ["other.py"]),
        ]
        first = select_best_candidate(list(cands)).index
        for _ in range(5):
            assert select_best_candidate(list(cands)).index == first
