"""self-consistency SWE-bench baseline: majority vote + the run wrapper.

A fake `anthropic` module is injected via sys.modules so these run with
or without the real SDK installed and never make a network call. swe_bench
is loaded by path (like test_swe_bench_harness) so the test works without
benchmarks/ being on sys.path.
"""
import importlib.util
import sys
import types
from pathlib import Path


def _load_swe_bench():
    if "swe_bench" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "swe_bench", Path(__file__).resolve().parent / "swe_bench.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["swe_bench"] = module
        spec.loader.exec_module(module)
    return sys.modules["swe_bench"]


_sb = _load_swe_bench()
_majority_patch = _sb._majority_patch
run_sonnet_self_consistency_n8 = _sb.run_sonnet_self_consistency_n8
run_sonnet_single = _sb.run_sonnet_single


# ---- _majority_patch ----

def test_majority_patch_picks_most_common():
    a = "--- a/x\n+++ b/x\n+win\n"
    b = "--- a/y\n+++ b/y\n+lose\n"
    assert _majority_patch([a, b, a, a, b]) == a


def test_majority_patch_normalizes_trailing_whitespace():
    a = "--- a/x\n+line"
    a_ws = "--- a/x  \n+line   "  # same patch, trailing spaces
    out = _majority_patch([a, a_ws, "--- a/z\n+other"])
    assert out in (a, a_ws)


def test_majority_patch_empty():
    assert _majority_patch([]) == ""


def test_majority_patch_tie_breaks_to_earliest():
    a = "--- a/a\n+a"
    b = "--- a/b\n+b"
    assert _majority_patch([a, b]) == a  # tie -> first seen


# ---- run wrapper (fake Anthropic) ----

class _Usage:
    input_tokens = 10
    output_tokens = 5


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = _Usage()


def _fake_anthropic(scripted):
    seq = list(scripted)
    state = {"i": 0}

    class _Messages:
        def create(self, **kwargs):
            text = seq[state["i"] % len(seq)]
            state["i"] += 1
            return _Resp(text)

    class _Anthropic:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = _Anthropic
    return mod


def _install(monkeypatch, scripted):
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic(scripted))


def test_self_consistency_votes_winner(monkeypatch):
    monkeypatch.delenv("MAVERICK_BENCH_DRY_RUN", raising=False)
    monkeypatch.setenv("MAVERICK_BENCH_SC_N", "5")
    # 3x WIN, 2x LOSE across 5 samples -> WIN wins
    _install(monkeypatch, ["WIN", "LOSE", "WIN", "LOSE", "WIN"])
    row = run_sonnet_self_consistency_n8("inst-1", "fix the bug")
    assert row.pipeline == "sonnet_self_consistency_n8"
    assert row.predicted_patch == "WIN"
    assert row.outcome == "success"
    assert row.tokens_in == 50  # 5 calls * 10
    assert row.tokens_out == 25


def test_self_consistency_sanitizes_formula_patch(monkeypatch):
    monkeypatch.delenv("MAVERICK_BENCH_DRY_RUN", raising=False)
    monkeypatch.setenv("MAVERICK_BENCH_SC_N", "3")
    _install(monkeypatch, ["=2+3", "=2+3", "--- a/safe\n"])
    row = run_sonnet_self_consistency_n8("inst-formula", "brief")
    assert row.predicted_patch == "'=2+3"
    assert row.outcome == "success"


def test_sonnet_single_sanitizes_formula_patch(monkeypatch):
    monkeypatch.delenv("MAVERICK_BENCH_DRY_RUN", raising=False)
    _install(monkeypatch, ["@SUM(1,2)"])
    row = run_sonnet_single("inst-single-formula", "brief")
    assert row.predicted_patch == "'@SUM(1,2)"
    assert row.outcome == "success"


def test_self_consistency_all_empty_is_empty(monkeypatch):
    monkeypatch.delenv("MAVERICK_BENCH_DRY_RUN", raising=False)
    monkeypatch.setenv("MAVERICK_BENCH_SC_N", "3")
    _install(monkeypatch, ["   ", "", "  \n "])
    row = run_sonnet_self_consistency_n8("inst-2", "brief")
    assert row.predicted_patch == ""
    assert row.outcome == "empty"


def test_self_consistency_dry_run(monkeypatch):
    monkeypatch.setenv("MAVERICK_BENCH_DRY_RUN", "1")
    row = run_sonnet_self_consistency_n8("inst-3", "brief")
    # dry-run must not touch Anthropic and must not be "not-implemented"
    assert row.outcome != "not-implemented"
    assert row.pipeline == "sonnet_self_consistency_n8"
