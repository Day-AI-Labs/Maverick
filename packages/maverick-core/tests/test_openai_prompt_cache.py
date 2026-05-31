"""OpenAI write-side prompt-cache ordering tests.

No API calls. The openai SDK is mocked so OpenAIClient can be constructed
without the real client, then ``_build_kwargs`` is exercised directly.

OpenAI's automatic prompt cache hits on the longest common prefix of a
request (>= ~1024 tokens): system + tools + leading messages must be
byte-identical across calls. These tests lock in the cache-friendly
ordering for gpt-4.1 / o-series with a long stable prefix.
"""
from __future__ import annotations

import sys

import pytest
from maverick.providers.openai_provider import OpenAIClient


class _FakeClient:
    def __init__(self, api_key=None, base_url=None, timeout=None):
        pass


class _FakeModule:
    OpenAI = _FakeClient
    AsyncOpenAI = _FakeClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", _FakeModule())
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    return OpenAIClient()


# A system prompt well over the ~1024-token (4 chars/token) min so the
# auto-cache reordering actually engages.
_LONG_SYSTEM = "You are a careful, long-horizon agent. " * 200

_UNSORTED_TOOLS = [
    {"name": "zebra", "description": "z", "input_schema": {"type": "object"}},
    {"name": "alpha", "description": "a", "input_schema": {"type": "object"}},
    {"name": "mike", "description": "m", "input_schema": {"type": "object"}},
]


def _tool_names(kwargs):
    return [t["function"]["name"] for t in kwargs["tools"]]


class TestCacheFriendlyOrdering:
    def test_system_leads_and_user_trails(self, client):
        kwargs = client._build_kwargs(
            _LONG_SYSTEM,
            [{"role": "user", "content": "the volatile question"}],
            _UNSORTED_TOOLS,
            max_tokens=256,
            model="gpt-4.1",
        )
        msgs = kwargs["messages"]
        # Stable prefix leads (system first), volatile user turn trails.
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == _LONG_SYSTEM
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "the volatile question"

    def test_tools_sorted_for_stable_prefix(self, client):
        kwargs = client._build_kwargs(
            _LONG_SYSTEM, [{"role": "user", "content": "q"}],
            _UNSORTED_TOOLS, max_tokens=256, model="gpt-4.1",
        )
        assert _tool_names(kwargs) == ["alpha", "mike", "zebra"]

    def test_ordering_stable_across_two_calls(self, client):
        # Differently-ordered tool inputs must produce the same prefix so
        # the second call hits OpenAI's auto-cache instead of busting it.
        first = client._build_kwargs(
            _LONG_SYSTEM, [{"role": "user", "content": "first"}],
            _UNSORTED_TOOLS, max_tokens=256, model="o3",
        )
        reordered = list(reversed(_UNSORTED_TOOLS))
        second = client._build_kwargs(
            _LONG_SYSTEM, [{"role": "user", "content": "second"}],
            reordered, max_tokens=256, model="o3",
        )
        assert _tool_names(first) == _tool_names(second)
        assert first["messages"][0] == second["messages"][0]

    def test_small_prefix_not_reordered(self, client):
        # Below the ~1024-token min the cache can't engage, so we leave the
        # caller's tool order untouched (no behaviour change on small prompts).
        kwargs = client._build_kwargs(
            "short system", [{"role": "user", "content": "q"}],
            _UNSORTED_TOOLS, max_tokens=256, model="gpt-4.1",
        )
        assert _tool_names(kwargs) == ["zebra", "alpha", "mike"]

    def test_non_cache_model_not_reordered(self, client):
        # gpt-4o has no automatic prompt cache; leave order as-is even with
        # a long prefix.
        kwargs = client._build_kwargs(
            _LONG_SYSTEM, [{"role": "user", "content": "q"}],
            _UNSORTED_TOOLS, max_tokens=256, model="gpt-4o",
        )
        assert _tool_names(kwargs) == ["zebra", "alpha", "mike"]

    def test_input_list_not_mutated(self, client):
        original = list(_UNSORTED_TOOLS)
        client._build_kwargs(
            _LONG_SYSTEM, [{"role": "user", "content": "q"}],
            _UNSORTED_TOOLS, max_tokens=256, model="gpt-4.1",
        )
        # sorted() returns a new list; the caller's list is unchanged.
        assert _UNSORTED_TOOLS == original
