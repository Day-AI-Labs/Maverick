"""Replayable trace format (ROADMAP 2028 H1)."""
from __future__ import annotations

from maverick.replay_trace import TraceWriter, read_trace, replay


def test_write_then_read_roundtrip(tmp_path):
    path = tmp_path / "run.jsonl"
    with TraceWriter(path) as w:
        s1 = w.record("tool_call", name="read_file", args={"path": "a"})
        s2 = w.record("llm_turn", tokens=42)
    assert (s1, s2) == (1, 2)
    events = read_trace(path)
    assert [e["kind"] for e in events] == ["tool_call", "llm_turn"]
    assert events[0]["seq"] == 1
    assert events[0]["args"] == {"path": "a"}
    assert "t" in events[0]


def test_tolerates_corrupt_trailing_line(tmp_path):
    path = tmp_path / "run.jsonl"
    with TraceWriter(path) as w:
        w.record("a")
        w.record("b")
    # simulate a half-written final record (process killed mid-flush)
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 3, "kind": "c", "x":')
    events = read_trace(path)
    assert [e["kind"] for e in events] == ["a", "b"]


def test_non_serialisable_field_coerced(tmp_path):
    path = tmp_path / "run.jsonl"

    class Weird:
        def __str__(self):
            return "weird-obj"

    with TraceWriter(path) as w:
        w.record("x", obj=Weird())
    assert read_trace(path)[0]["obj"] == "weird-obj"


def test_replay_dispatches_in_seq_order(tmp_path):
    path = tmp_path / "run.jsonl"
    with TraceWriter(path) as w:
        w.record("tool", name="one")
        w.record("llm")
        w.record("tool", name="two")
    seen: list[str] = []
    n = replay(path, {
        "tool": lambda e: seen.append(f"tool:{e['name']}"),
        "*": lambda e: seen.append(e["kind"]),
    })
    assert n == 3
    assert seen == ["tool:one", "llm", "tool:two"]


def test_read_missing_file_is_empty(tmp_path):
    assert read_trace(tmp_path / "nope.jsonl") == []
