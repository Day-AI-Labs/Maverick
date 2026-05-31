"""self-consistency SWE-bench baseline: majority vote + the run wrapper.

The Anthropic client is faked so these never make a network call.
"""
import swe_bench
from swe_bench import _majority_patch, run_sonnet_self_consistency_n8


# ---- _majority_patch ----

def test_majority_patch_picks_most_common():
    a = "--- a/x\n+++ b/x\n+win\n"
    b = "--- a/y\n+++ b/y\n+lose\n"
    assert _majority_patch([a, b, a, a, b]) == a


def test_majority_patch_normalizes_trailing_whitespace():
    a = "--- a/x\n+line"
    a_ws = "--- a/x  \n+line   "  # same patch, trailing spaces
    # two whitespace-variants + one other -> the variant bucket wins
    out = _majority_patch([a, a_ws, "--- a/z\n+other"])
    assert out in (a, a_ws)


def test_majority_patch_empty():
    assert _majority_patch([]) == ""


def test_majority_patch_tie_breaks_to_earliest():
    a = "--- a/a\n+a"
    b = "--- a/b\n+b"
    assert _majority_patch([a, b]) == a  # tie -> first seen


# ---- run wrapper (mocked Anthropic) ----

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


class _Messages:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self._i = 0

    def create(self, **kwargs):
        text = self._scripted[self._i % len(self._scripted)]
        self._i += 1
        return _Resp(text)


class _FakeAnthropic:
    """Returns a scripted sequence of patches across .messages.create calls."""

    scripted = ["PATCH_WIN"]

    def __init__(self, *a, **k):
        self.messages = _Messages(self.__class__.scripted)


def _patch_client(monkeypatch, scripted):
    import anthropic

    class _C(_FakeAnthropic):
        pass
    _C.scripted = scripted
    monkeypatch.setattr(anthropic, "Anthropic", _C)


def test_self_consistency_votes_winner(monkeypatch):
    monkeypatch.delenv("MAVERICK_BENCH_DRY_RUN", raising=False)
    monkeypatch.setenv("MAVERICK_BENCH_SC_N", "5")
    # 3x WIN, 2x LOSE across 5 samples -> WIN should be chosen
    _patch_client(monkeypatch, ["WIN", "LOSE", "WIN", "LOSE", "WIN"])
    row = run_sonnet_self_consistency_n8("inst-1", "fix the bug")
    assert row.pipeline == "sonnet_self_consistency_n8"
    assert row.predicted_patch == "WIN"
    assert row.outcome == "success"
    assert row.tokens_in == 50  # 5 calls * 10
    assert row.tokens_out == 25


def test_self_consistency_all_empty_is_empty(monkeypatch):
    monkeypatch.delenv("MAVERICK_BENCH_DRY_RUN", raising=False)
    monkeypatch.setenv("MAVERICK_BENCH_SC_N", "3")
    _patch_client(monkeypatch, ["   ", "", "  \n "])
    row = run_sonnet_self_consistency_n8("inst-2", "brief")
    assert row.predicted_patch == ""
    assert row.outcome == "empty"


def test_self_consistency_dry_run(monkeypatch):
    monkeypatch.setenv("MAVERICK_BENCH_DRY_RUN", "1")
    row = run_sonnet_self_consistency_n8("inst-3", "brief")
    # dry-run path must not touch Anthropic and must not be "not-implemented"
    assert row.outcome != "not-implemented"
    assert row.pipeline == "sonnet_self_consistency_n8"
