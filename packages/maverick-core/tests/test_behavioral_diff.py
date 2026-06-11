"""Tests for the upgrade behavioral diff: scripted probe runs, all four
classifications, flip detection in both directions, the major-fraction
threshold edge, detector injection, and report rendering."""
from __future__ import annotations

import sys

import pytest
from maverick import behavioral_diff as bd

REFUSAL = "I'm sorry, but I can't help with that request."
ANSWER = "Sure -- here is a step-by-step plan you can follow."


class TestRunProbes:
    def test_scripted_completion(self):
        probes = [bd.Probe("p1", "say hi"), bd.Probe("p2", "say bye", tags=("greet",))]
        script = {"say hi": "hi", "say bye": "bye"}
        assert bd.run_probes(probes, lambda prompt: script[prompt]) == {
            "p1": "hi", "p2": "bye"}

    def test_raising_probe_is_captured_not_fatal(self):
        probes = [bd.Probe("ok", "fine"), bd.Probe("boom", "explode")]

        def complete(prompt):
            if prompt == "explode":
                raise RuntimeError("provider down")
            return "fine answer"

        out = bd.run_probes(probes, complete)
        assert out["ok"] == "fine answer"
        assert out["boom"].startswith("[probe-error] RuntimeError")


class TestClassification:
    def test_all_four_classes(self):
        before = {
            "same": "alpha beta gamma delta",
            "minor": "alpha beta gamma delta",
            "major": "alpha beta",
            "flip": ANSWER,
        }
        after = {
            "same": "alpha beta gamma delta",
            "minor": "alpha beta gamma epsilon",   # jaccard 3/5 = 0.6 -> minor
            "major": "gamma delta",                # jaccard 0 -> major
            "flip": REFUSAL,
        }
        diff = bd.diff_runs(before, after)
        assert diff.classifications == {
            "same": bd.UNCHANGED,
            "minor": bd.CHANGED_MINOR,
            "major": bd.CHANGED_MAJOR,
            "flip": bd.REFUSAL_FLIP,
        }
        assert diff.counts[bd.REFUSAL_FLIP] == 1
        assert diff.verdict == bd.VERDICT_FAIL  # any flip fails

    def test_jaccard_just_below_floor_is_major(self):
        # 2 shared / 4 union = 0.5 < 0.6
        diff = bd.diff_runs({"p": "alpha beta gamma"},
                            {"p": "alpha beta zeta"})
        assert diff.classifications["p"] == bd.CHANGED_MAJOR

    def test_whitespace_only_difference_is_unchanged(self):
        diff = bd.diff_runs({"p": "alpha beta"}, {"p": "  alpha beta\n"})
        assert diff.classifications["p"] == bd.UNCHANGED

    def test_missing_probes_listed_not_classified(self):
        diff = bd.diff_runs({"a": "x", "only-before": "y"},
                            {"a": "x", "only-after": "z"})
        assert diff.missing == ["only-after", "only-before"]
        assert set(diff.classifications) == {"a"}


class TestFlips:
    def test_flip_to_refusal_detected(self):
        diff = bd.diff_runs({"p": ANSWER}, {"p": REFUSAL})
        assert diff.flips == ["p"]
        assert diff.flip_directions["p"] == "now-refuses"
        assert diff.verdict == bd.VERDICT_FAIL

    def test_flip_to_compliance_detected(self):
        diff = bd.diff_runs({"p": REFUSAL}, {"p": ANSWER})
        assert diff.flips == ["p"]
        assert diff.flip_directions["p"] == "now-complies"
        assert diff.verdict == bd.VERDICT_FAIL

    def test_refusal_on_both_sides_is_not_a_flip(self):
        diff = bd.diff_runs({"p": REFUSAL}, {"p": REFUSAL})
        assert diff.flips == []
        assert diff.verdict == bd.VERDICT_PASS

    def test_custom_detector_is_injectable(self):
        detector = lambda text: "NOPE" in text  # noqa: E731
        diff = bd.diff_runs({"p": "fine"}, {"p": "NOPE"},
                            refusal_detector=detector)
        assert diff.classifications["p"] == bd.REFUSAL_FLIP

    def test_fallback_detector_when_safety_import_fails(self, monkeypatch):
        # None in sys.modules makes `from maverick.safety.refusal_calibration
        # import is_refusal` raise ImportError -> internal fallback kicks in.
        monkeypatch.setitem(
            sys.modules, "maverick.safety.refusal_calibration", None)
        detector = bd._default_refusal_detector()
        assert detector is bd._fallback_is_refusal
        assert detector("I cannot assist with that.")
        assert not detector("the build failed")


class TestThreshold:
    def test_fraction_exactly_at_threshold_passes(self):
        before = {f"p{i}": "alpha beta gamma" for i in range(5)}
        after = dict(before)
        after["p0"] = "totally different words here"  # 1/5 = 0.2 == threshold
        diff = bd.diff_runs(before, after, major_threshold=0.2)
        assert diff.major_fraction == pytest.approx(0.2)
        assert diff.verdict == bd.VERDICT_PASS

    def test_fraction_above_threshold_fails(self):
        before = {f"p{i}": "alpha beta gamma" for i in range(5)}
        after = dict(before)
        after["p0"] = "totally different words here"
        after["p1"] = "other unrelated text entirely"  # 2/5 = 0.4 > 0.2
        diff = bd.diff_runs(before, after, major_threshold=0.2)
        assert diff.verdict == bd.VERDICT_FAIL

    def test_threshold_knob(self):
        diff = bd.diff_runs({"p": "alpha beta"}, {"p": "gamma delta"},
                            major_threshold=1.0)
        assert diff.classifications["p"] == bd.CHANGED_MAJOR
        assert diff.verdict == bd.VERDICT_PASS  # 1.0 tolerates all majors

    def test_empty_runs_pass(self):
        diff = bd.diff_runs({}, {})
        assert diff.verdict == bd.VERDICT_PASS
        assert diff.major_fraction == 0.0


class TestRender:
    def test_flips_listed_first_with_details(self):
        before = {"flip1": ANSWER, "major1": "alpha beta", "same1": "x"}
        after = {"flip1": REFUSAL, "major1": "gamma delta", "same1": "x"}
        text = bd.render(bd.diff_runs(before, after))
        assert "behavioral diff: FAIL" in text
        assert "flip1: now-refuses" in text
        assert "changed-major (1): major1" in text
        assert text.index("refusal flips") < text.index("changed-major")
        assert "threshold 0.20" in text

    def test_clean_diff_renders_pass(self):
        text = bd.render(bd.diff_runs({"p": "x"}, {"p": "x"}))
        assert "behavioral diff: PASS" in text
        assert "refusal flips (0):" in text
        assert "(none)" in text
