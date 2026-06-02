"""Regression tests for issue #478 — context/memory correctness.

Covers four independent fixes:
  1. compaction embedding ranking must not drop head turns when the
     embedder yields fewer vectors than there are head messages;
  2. ``_fit_recent_to_budget`` must stop (not append blank turns) once
     the token budget is exhausted;
  3. session-provider SSE parsing must join multi-line ``data:`` fields
     into a single event payload;
  4. reflexion ``recall`` must prefer fresher lessons and de-duplicate
     near-identical ones in the top-k.
"""
from __future__ import annotations

import builtins
import sys
import time
import types

from maverick import context_compactor as cc
from maverick import reflexion
from maverick.session_providers.base import iter_sse_data_payloads

# --- Task 1: embedding ranking keeps head turns on vector shortfall ------

class _ShortEmbedder:
    """Embedder that yields a query vector but FEWER doc vectors than asked,
    mimicking empty-text / batching shortfalls."""

    def __init__(self, model_name=None):
        self._first = True

    def embed(self, texts):
        texts = list(texts)
        # The query call passes a single string; yield one vector for it.
        if len(texts) == 1:
            yield [1.0, 0.0]
            return
        # The doc call: deliberately yield one fewer vector than requested.
        for _ in texts[:-1]:
            yield [1.0, 0.0]


def test_embedding_shortfall_keeps_all_head_turns(monkeypatch):
    head = [
        {"role": "user", "content": "first turn about apples"},
        {"role": "assistant", "content": "second turn about oranges"},
        {"role": "user", "content": "third turn about pears"},
    ]

    # _score_by_embedding does ``from fastembed import TextEmbedding`` at
    # call time; inject a fake module so the import resolves to our stub.
    fake_mod = types.ModuleType("fastembed")
    fake_mod.TextEmbedding = _ShortEmbedder
    monkeypatch.setitem(sys.modules, "fastembed", fake_mod)
    scored = cc._score_by_embedding(head, "fruit query", None)

    # Every head turn must be represented exactly once -- none dropped.
    assert len(scored) == len(head)
    assert sorted(i for _, i, _ in scored) == [0, 1, 2]
    # The turn lacking a vector (index 2) is KEPT with max score, not culled.
    last = next(s for s, i, _ in scored if i == 2)
    assert last == float("inf")


# --- Task 2: budget exhaustion drops tail turns, never blanks them -------

def test_fit_recent_to_budget_drops_rather_than_blanks():
    # Three turns, each ~5 tokens; budget only fits the newest one.
    messages = [
        {"role": "user", "content": "aaaa bbbb cccc dddd"},
        {"role": "assistant", "content": "eeee ffff gggg hhhh"},
        {"role": "user", "content": "iiii jjjj kkkk llll"},
    ]
    newest_cost = cc._approx_tokens(cc._message_text(messages[-1]))
    fitted, _ = cc._fit_recent_to_budget(messages, newest_cost)

    # Only the newest turn survives; older turns are dropped outright.
    assert fitted == [messages[-1]]
    # No empty-content turn was appended.
    assert all(cc._message_text(m) != "" for m in fitted)


def test_fit_recent_to_budget_no_blank_partial_when_exhausted():
    messages = [
        {"role": "user", "content": "x" * 40},
        {"role": "assistant", "content": "y" * 40},
    ]
    # Budget fits the newest turn exactly, leaving zero for the older one.
    newest_cost = cc._approx_tokens(cc._message_text(messages[-1]))
    fitted, remaining = cc._fit_recent_to_budget(messages, newest_cost)
    assert remaining == 0
    assert len(fitted) == 1
    assert cc._message_text(fitted[0]) == messages[-1]["content"]


# --- Task 3: multi-line data: SSE events parse as one payload ------------

def test_sse_joins_multiline_data_field():
    # A spec-compliant event whose JSON is pretty-printed across lines.
    stream = (
        "event: message\n"
        "data: {\n"
        'data:   "completion": "hi"\n'
        "data: }\n"
        "\n"
        "data: [DONE]\n"
        "\n"
    )
    payloads = list(iter_sse_data_payloads(stream))
    assert payloads[0] == '{\n  "completion": "hi"\n}'
    assert payloads[1] == "[DONE]"


def test_sse_claude_parser_handles_multiline_event():
    from maverick.session_providers.claude_session import _parse_sse_response

    stream = (
        "data: {\n"
        'data:   "completion": "Hello,"\n'
        "data: }\n"
        "\n"
        'data: {"completion": " world"}\n'
        "\n"
        "data: [DONE]\n"
        "\n"
    )
    assert _parse_sse_response(stream) == "Hello, world"


def test_sse_single_line_events_still_work():
    stream = (
        'data: {"a": 1}\n'
        "\n"
        'data: {"b": 2}\n'
        "\n"
    )
    assert list(iter_sse_data_payloads(stream)) == ['{"a": 1}', '{"b": 2}']


# --- Task 4: reflexion recall prefers recent + dedups --------------------

def test_recall_prefers_recent_on_equal_similarity(tmp_path):
    path = tmp_path / "reflexions.ndjson"
    now = time.time()
    # Two equally-similar lessons; the fresher one must rank first.
    reflexion.record(
        goal_text="fix the parser bug now",
        failure_class="agent_error",
        failure_msg="stale",
        reflection="old lesson",
        path=path,
    )
    # Force timestamps: rewrite with explicit ts so the test is deterministic.
    import json
    lines = [
        json.dumps({
            "ts": now - 10_000, "goal_text": "fix the parser bug now",
            "failure_class": "agent_error", "failure_msg": "stale",
            "reflection": "old lesson", "tools_used": [],
            "channel": None, "user_id": None,
        }),
        json.dumps({
            "ts": now, "goal_text": "fix the parser bug now please",
            "failure_class": "agent_error", "failure_msg": "fresh",
            "reflection": "new lesson", "tools_used": [],
            "channel": None, "user_id": None,
        }),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    hits = reflexion.recall("fix the parser bug now", path=path, k=2)
    assert hits
    # The fresher lesson outranks the older one despite similar similarity.
    assert hits[0][1].failure_msg == "fresh"


def test_recall_dedupes_near_identical_lessons(tmp_path):
    path = tmp_path / "reflexions.ndjson"
    import json
    now = time.time()
    rows = [
        {"ts": now, "goal_text": "deploy the service to staging",
         "failure_class": "agent_error", "failure_msg": "dup-a",
         "reflection": "x", "tools_used": [], "channel": None, "user_id": None},
        {"ts": now - 1, "goal_text": "deploy the service to staging",
         "failure_class": "agent_error", "failure_msg": "dup-b",
         "reflection": "x", "tools_used": [], "channel": None, "user_id": None},
        {"ts": now - 2, "goal_text": "deploy the service to staging area zone",
         "failure_class": "agent_error", "failure_msg": "dup-c",
         "reflection": "x", "tools_used": [], "channel": None, "user_id": None},
        {"ts": now - 3, "goal_text": "rotate database credentials safely",
         "failure_class": "agent_error", "failure_msg": "distinct",
         "reflection": "x", "tools_used": [], "channel": None, "user_id": None},
    ]
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8",
    )

    hits = reflexion.recall("deploy the service to staging", path=path, k=5)
    msgs = [h[1].failure_msg for h in hits]
    # The two identical "deploy ... staging" goals must collapse to one.
    assert msgs.count("dup-a") + msgs.count("dup-b") == 1


def test_recall_scan_cap_streams_without_reading_all_lines(tmp_path, monkeypatch):
    path = tmp_path / "reflexions.ndjson"
    path.touch()

    class IterOnlyFile:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            import json
            now = time.time()
            for i in range(5):
                yield json.dumps({
                    "ts": now + i,
                    "goal_text": f"target goal {i}",
                    "failure_class": "agent_error",
                    "failure_msg": f"kept-{i}",
                    "reflection": "x",
                    "tools_used": [],
                    "channel": None,
                    "user_id": None,
                }) + "\n"

        def readlines(self):
            raise AssertionError("recall must not materialize the whole log")

    def fake_open(open_path, *args, **kwargs):
        if open_path == path:
            return IterOnlyFile()
        return real_open(open_path, *args, **kwargs)

    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", fake_open)

    hits = reflexion.recall("target goal", path=path, scan_cap=2, k=5)
    assert [hit[1].failure_msg for hit in hits] == ["kept-4", "kept-3"]


def test_recall_scan_cap_limits_considered_lines(tmp_path):
    path = tmp_path / "reflexions.ndjson"
    import json
    now = time.time()
    rows = []
    # Old, highly-relevant lesson buried beyond the scan cap.
    rows.append({
        "ts": now - 1000, "goal_text": "optimize the image resizer pipeline",
        "failure_class": "agent_error", "failure_msg": "buried",
        "reflection": "x", "tools_used": [], "channel": None, "user_id": None,
    })
    # Many irrelevant recent rows pushing the buried one out of the window.
    for i in range(5):
        rows.append({
            "ts": now - i, "goal_text": f"unrelated chore number {i}",
            "failure_class": "agent_error", "failure_msg": "noise",
            "reflection": "x", "tools_used": [], "channel": None,
            "user_id": None,
        })
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8",
    )

    hits = reflexion.recall(
        "optimize the image resizer pipeline", path=path, scan_cap=3,
    )
    # With scan_cap=3 the buried first line is never considered.
    assert all(h[1].failure_msg != "buried" for h in hits)
