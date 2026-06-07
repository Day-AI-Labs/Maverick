"""Robustness of the session-provider simulated tool-call parser.

Session providers have no native function-calling, so tool use rides a markdown
protocol the model must emit and we must parse back. A parse failure here is a
*task* failure (the call is silently dropped and the agent stalls), so this
covers the model-drift cases the old lazy `\\{.*?\\}` regex got wrong --
nested-object args, trailing commas, code fences, no-arg calls -- while keeping
graceful drop for genuinely-malformed JSON.
"""
from __future__ import annotations

from maverick.session_providers.tool_simulator import _parse_tool_calls


def test_simple_named_call_still_parses():
    text = '<tool name="calc">{"x": 2, "y": 3}</tool>'
    cleaned, calls = _parse_tool_calls(text)
    assert cleaned == ""
    assert len(calls) == 1
    assert calls[0].name == "calc" and calls[0].input == {"x": 2, "y": 3}


def test_nested_object_args_survive():
    # The headline fix: a lazy `{.*?}` truncated at the first '}', dropping the
    # whole call. Balanced extraction keeps the nested object intact.
    text = '<tool name="write">{"path": "a.py", "edit": {"old": "x", "new": "y"}}</tool>'
    _, calls = _parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].input == {"path": "a.py", "edit": {"old": "x", "new": "y"}}


def test_trailing_comma_is_repaired():
    text = '<tool name="t">{"a": 1, "b": 2,}</tool>'
    _, calls = _parse_tool_calls(text)
    assert len(calls) == 1 and calls[0].input == {"a": 1, "b": 2}


def test_code_fenced_json_args():
    text = '<tool name="t">```json\n{"a": 1}\n```</tool>'
    _, calls = _parse_tool_calls(text)
    assert len(calls) == 1 and calls[0].input == {"a": 1}


def test_brace_inside_string_value():
    text = '<tool name="t">{"a": "}", "b": "{x}"}</tool>'
    _, calls = _parse_tool_calls(text)
    assert len(calls) == 1 and calls[0].input == {"a": "}", "b": "{x}"}


def test_no_arg_named_call():
    _, calls = _parse_tool_calls('<tool name="list_dir"></tool>')
    assert len(calls) == 1 and calls[0].name == "list_dir" and calls[0].input == {}


def test_no_arg_inline_call():
    _, calls = _parse_tool_calls("<tool>list_dir()</tool>")
    assert len(calls) == 1 and calls[0].name == "list_dir" and calls[0].input == {}


def test_inline_form_with_nested_args():
    text = '<tool>search({"q": "x", "opts": {"limit": 5}})</tool>'
    _, calls = _parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].name == "search"
    assert calls[0].input == {"q": "x", "opts": {"limit": 5}}


def test_multiple_calls_and_prose_retained():
    text = (
        "Let me do two things.\n"
        '<tool name="a">{"k": {"n": 1}}</tool>\n'
        "and then\n"
        '<tool name="b">{"m": 2}</tool>\n'
        "done."
    )
    cleaned, calls = _parse_tool_calls(text)
    assert [c.name for c in calls] == ["a", "b"]
    assert calls[0].input == {"k": {"n": 1}}
    assert "Let me do two things." in cleaned and "done." in cleaned
    assert "<tool" not in cleaned


def test_malformed_json_is_dropped_gracefully():
    # An unbalanced/garbage object can't be parsed -> drop the call (no crash),
    # leaving the surrounding prose so the agent can react.
    text = 'before <tool name="t">{not valid</tool> after'
    cleaned, calls = _parse_tool_calls(text)
    assert calls == []
    assert "before" in cleaned and "after" in cleaned


def test_non_object_json_wrapped_as_raw():
    text = '<tool name="t">[1, 2, 3]</tool>'
    _, calls = _parse_tool_calls(text)
    # No leading '{' -> treated as a no-arg call (the array isn't valid args).
    assert len(calls) == 1 and calls[0].input == {}


def test_full_client_roundtrips_nested_call():
    from maverick.llm import LLMResponse
    from maverick.session_providers.tool_simulator import SimulatedToolCallClient

    class _Inner:
        DEFAULT_MODEL = "x"

        def complete(self, **kw):
            return LLMResponse(
                text='ok\n<tool name="write">{"path": "a", "edit": {"o": 1}}</tool>',
                thinking=None, tool_calls=[], stop_reason="end_turn",
            )

    resp = SimulatedToolCallClient(_Inner()).complete(
        system="s", messages=[], tools=[{"name": "write", "description": "w"}],
    )
    assert resp.stop_reason == "tool_use"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].input == {"path": "a", "edit": {"o": 1}}
