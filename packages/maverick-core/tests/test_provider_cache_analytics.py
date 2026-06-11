"""Provider cache analytics: hit rate, savings math, per-role, recommendations."""
from __future__ import annotations

from maverick.provider_cache_analytics import analyze, render


def _row(kind, tokens, role="default", model=None):
    r = {"kind": kind, "tokens": tokens, "role": role}
    if model:
        r["model"] = model
    return r


def test_empty_rows():
    rep = analyze([])
    assert rep["overall"]["hit_rate"] == 0.0
    assert "no cacheable input tokens" in rep["recommendations"][0]


def test_hit_rate_math():
    # 80 read + 20 uncached -> 80% hit rate
    rep = analyze([_row("read", 80), _row("uncached", 20)])
    assert rep["overall"]["hit_rate"] == 0.8
    assert rep["overall"]["read"] == 80 and rep["overall"]["uncached"] == 20


def test_savings_at_configured_price():
    # 1M read tokens at $3/1M input, Anthropic 0.1x read -> saves 0.9 * $3 = $2.70
    rep = analyze([_row("read", 1_000_000, model="m")], prices={"m": 3.0})
    assert rep["overall"]["saved"] == 2.7


def test_write_surcharge():
    # 1M write tokens at $3/1M, 1.25x write -> 0.25 * $3 = $0.75 surcharge
    rep = analyze([_row("creation", 1_000_000, model="m")], prices={"m": 3.0})
    assert rep["overall"]["write_cost"] == 0.75
    assert rep["overall"]["write"] == 1_000_000


def test_net_saved_combines_read_and_write():
    rows = [_row("read", 1_000_000, model="m"), _row("creation", 1_000_000, model="m")]
    rep = analyze(rows, prices={"m": 3.0})
    assert rep["overall"]["net_saved"] == round(2.7 - 0.75, 4)


def test_kind_aliases_normalised():
    rows = [_row("cache_read", 50), _row("cache-write", 10), _row("input", 50)]
    rep = analyze(rows)
    assert rep["overall"]["read"] == 50
    assert rep["overall"]["write"] == 10
    assert rep["overall"]["uncached"] == 50


def test_openai_read_multiplier():
    # OpenAI auto-cache reads at 0.5x -> saves only 0.5 * price
    rep = analyze([_row("read", 1_000_000, model="m")], prices={"m": 4.0}, read_mult=0.5)
    assert rep["overall"]["saved"] == 2.0


def test_per_role_breakdown():
    rows = [
        _row("read", 90, role="verifier"), _row("uncached", 10, role="verifier"),
        _row("read", 1, role="planner"), _row("uncached", 99, role="planner"),
    ]
    rep = analyze(rows)
    assert rep["by_role"]["verifier"]["hit_rate"] == 0.9
    assert rep["by_role"]["planner"]["hit_rate"] == 0.01


def test_unstable_prefix_recommendation():
    # planner: low hit rate over a meaningful volume -> flagged as unstable prefix
    rows = [
        _row("read", 1_000, role="planner"),
        _row("uncached", 99_000, role="planner"),
    ]
    rep = analyze(rows)
    assert any("planner" in r and "unstable" in r for r in rep["recommendations"])


def test_no_unstable_flag_below_volume_threshold():
    # tiny volume, low hit rate -> not enough signal to advise
    rows = [_row("read", 1, role="tiny"), _row("uncached", 99, role="tiny")]
    rep = analyze(rows)
    assert not any("tiny" in r and "unstable" in r for r in rep["recommendations"])


def test_write_without_read_flagged():
    rows = [_row("creation", 50_000, model="m"), _row("uncached", 10)]
    rep = analyze(rows, prices={"m": 3.0})
    assert any("written but never read" in r for r in rep["recommendations"])


def test_bad_rows_skipped():
    rows = [
        _row("read", 50),
        {"kind": "bogus", "tokens": 999},      # unknown kind
        {"kind": "read", "tokens": "nope"},    # non-int tokens
        {"kind": "read", "tokens": 0},         # zero -> skipped
        _row("uncached", 50),
    ]
    rep = analyze(rows)
    assert rep["overall"]["read"] == 50 and rep["overall"]["uncached"] == 50


def test_default_price_when_model_absent():
    # no prices map -> flat $3 default; 1M read -> 0.9 * 3 = 2.70
    rep = analyze([_row("read", 1_000_000)])
    assert rep["overall"]["saved"] == 2.7


def test_duck_typed_rows():
    class Row:
        def __init__(self, kind, tokens):
            self.kind, self.tokens = kind, tokens

    rep = analyze([Row("read", 30), Row("uncached", 70)])
    assert rep["overall"]["hit_rate"] == 0.3


def test_render_table():
    rows = [
        _row("read", 80, role="verifier"), _row("uncached", 20, role="verifier"),
    ]
    out = render(analyze(rows))
    assert "provider cache analytics:" in out and "80%" in out
    assert "by role:" in out and "verifier" in out
    assert "recommendations:" in out


def test_render_empty():
    assert "no cacheable input tokens" in render(analyze([]))
