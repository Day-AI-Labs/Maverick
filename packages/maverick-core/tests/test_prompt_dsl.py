"""Cache-aware prompt assembly DSL: stable-first ordering + breakpoint + lint."""
from __future__ import annotations

from maverick.prompt_dsl import (
    PromptBuilder,
    Segment,
    Stability,
    lint_segments,
)


def test_orders_stable_before_volatile():
    p = (PromptBuilder()
         .volatile("user question", name="turn")
         .stable("system role", name="sys")
         .stable("tool catalog", name="tools")
         .volatile("timestamp 1700000000", name="ts")
         .assemble())
    # stable segments first, in insertion order; volatile after
    assert [s.name for s in p.segments] == ["sys", "tools", "turn", "ts"]


def test_breakpoint_marks_end_of_stable_prefix():
    p = (PromptBuilder()
         .stable("a").stable("b")
         .volatile("c")
         .assemble())
    assert p.breakpoint_index == 1  # last stable segment
    assert p.has_cacheable_prefix is True
    assert p.segments[p.breakpoint_index].text == "b"


def test_no_stable_prefix():
    p = PromptBuilder().volatile("only volatile").assemble()
    assert p.breakpoint_index == -1
    assert p.has_cacheable_prefix is False


def test_stable_and_volatile_text_halves():
    p = (PromptBuilder(joiner="|")
         .stable("s1").stable("s2")
         .volatile("v1")
         .assemble())
    assert p.stable_text == "s1|s2"
    assert p.volatile_text == "v1"


def test_empty_segments_skipped():
    p = PromptBuilder().stable("").volatile("real").assemble()
    assert [s.text for s in p.segments] == ["real"]


def test_cache_fingerprint_ignores_volatile():
    a = PromptBuilder().stable("same system").volatile("question A")
    b = PromptBuilder().stable("same system").volatile("question B")
    assert a.cache_fingerprint() == b.cache_fingerprint()
    c = PromptBuilder().stable("DIFFERENT system").volatile("question A")
    assert c.cache_fingerprint() != a.cache_fingerprint()


def test_lint_flags_suspect_stable_segment():
    segs = [Segment("you are a bot, request_id=abc", Stability.STABLE, name="sys")]
    problems = lint_segments(segs)
    assert any("bust the cache" in p for p in problems)
    segs2 = [Segment("ts=1700000000000", Stability.STABLE)]
    assert any("bust the cache" in p for p in lint_segments(segs2))


def test_lint_flags_stable_after_volatile():
    segs = [
        Segment("user turn", Stability.VOLATILE),
        Segment("clean system block", Stability.STABLE),
    ]
    problems = lint_segments(segs)
    assert any("follows a VOLATILE" in p for p in problems)


def test_lint_clean_when_well_formed():
    segs = [
        Segment("you are a helpful assistant", Stability.STABLE),
        Segment("tool catalog ...", Stability.STABLE),
        Segment("the user asks: hi", Stability.VOLATILE),
    ]
    assert lint_segments(segs) == []
