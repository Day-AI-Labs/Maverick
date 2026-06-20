"""Round-1 provider hardening regressions.

- A missing ``usage`` block aborts the turn for PAID providers (fail-closed) but
  NOT for self-hosted ollama/vllm/tgi (USAGE_REQUIRED=False): those price at $0,
  and many local OpenAI-compatible servers omit usage on non-streaming calls.
- Unparseable tool-call arguments are surfaced (warning), not silently swallowed.
"""
from __future__ import annotations

import logging

import pytest
from maverick.budget import Budget, BudgetExceeded
from maverick.providers.ollama_provider import OllamaClient
from maverick.providers.openai_provider import OpenAIClient


class _Msg:
    def __init__(self, content="hi", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.reasoning_content = None


class _Choice:
    def __init__(self, msg, finish_reason="stop"):
        self.message = msg
        self.finish_reason = finish_reason


class _Resp:
    """An OpenAI-compatible response with NO usage block."""
    def __init__(self, msg, usage=None):
        self.choices = [_Choice(msg)]
        self.usage = usage


def test_paid_provider_missing_usage_aborts():
    # USAGE_REQUIRED is True on the base/paid client -> fail closed.
    budget = Budget(max_dollars=10.0)
    with pytest.raises(BudgetExceeded, match="missing token usage"):
        OpenAIClient._from_response(_Resp(_Msg()), budget, model="gpt-4o",
                                    usage_required=True)


def test_self_hosted_missing_usage_does_not_abort():
    # ollama/vllm/tgi set USAGE_REQUIRED=False; a usage-less response must NOT
    # raise -- it records a $0 zero-token call and returns the text.
    assert OllamaClient.USAGE_REQUIRED is False
    budget = Budget(max_dollars=10.0)
    r = OpenAIClient._from_response(_Resp(_Msg("local answer")), budget,
                                    model="llama3.3:70b",
                                    price_model_prefix="ollama:",
                                    usage_required=False)
    assert r.text == "local answer"
    # $0 self-hosted: nothing was billed.
    assert budget.dollars == 0.0


class _BadArgsToolCall:
    class function:
        name = "do_thing"
        arguments = "{not valid json"
    id = "call_1"


def test_unparseable_tool_args_warns_and_uses_empty(caplog):
    msg = _Msg(tool_calls=[_BadArgsToolCall()])
    with caplog.at_level(logging.WARNING, logger="maverick.providers.openai_provider"):
        r = OpenAIClient._from_response(_Resp(msg), None)
    assert r.tool_calls and r.tool_calls[0].input == {}
    assert any("unparseable arguments" in rec.message for rec in caplog.records)
