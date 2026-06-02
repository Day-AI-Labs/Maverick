"""Shared tool-reliability policy at the dispatch chokepoint."""
from __future__ import annotations

import asyncio

import pytest
from maverick import tool_reliability
from maverick.tools import Tool, ToolRegistry


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # Keep backoff sleeps out of the test clock.
    async def _instant(_delay):
        return None
    monkeypatch.setattr(tool_reliability.asyncio, "sleep", _instant)


def _transient() -> Exception:
    # "connection refused" -> TRANSIENT_NETWORK in retry_classifier.
    return ConnectionError("connection refused by upstream")


class TestRunWithRetry:
    def test_transient_failure_is_retried_then_succeeds(self):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise _transient()
            return "ok"

        # "my_lookup" is unlisted -> defaults to medium -> retry-safe.
        out = asyncio.run(tool_reliability.run_with_retry("my_lookup", flaky))
        assert out == "ok"
        assert calls["n"] == 3

    def test_high_risk_tool_is_not_retried(self):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            raise _transient()

        # "shell" is high-risk: a transient error must not auto-re-fire it.
        with pytest.raises(ConnectionError):
            asyncio.run(tool_reliability.run_with_retry("shell", flaky))
        assert calls["n"] == 1

    def test_deterministic_error_is_not_retried(self):
        calls = {"n": 0}

        async def boom():
            calls["n"] += 1
            raise ValueError("bad argument")  # classifies UNKNOWN

        with pytest.raises(ValueError):
            asyncio.run(tool_reliability.run_with_retry("my_lookup", boom))
        assert calls["n"] == 1

    def test_terminal_auth_error_is_not_retried(self):
        calls = {"n": 0}

        async def boom():
            calls["n"] += 1
            raise RuntimeError("401 unauthorized")  # AUTH -> terminal

        with pytest.raises(RuntimeError):
            asyncio.run(tool_reliability.run_with_retry("my_lookup", boom))
        assert calls["n"] == 1

    def test_is_retry_safe_by_risk(self):
        assert tool_reliability.is_retry_safe("web_search") is True   # default medium
        assert tool_reliability.is_retry_safe("shell") is False       # high
        assert tool_reliability.is_retry_safe("email") is False       # high


class TestRegistryIntegration:
    def test_registry_retries_retry_safe_tool(self):
        calls = {"n": 0}

        def flaky(_args):
            calls["n"] += 1
            if calls["n"] < 2:
                raise _transient()
            return "recovered"

        reg = ToolRegistry()
        reg.register(Tool(name="flaky_read", description="d",
                          input_schema={"type": "object", "properties": {}},
                          fn=flaky))
        out = asyncio.run(reg.run("flaky_read", {}))
        assert out == "recovered"
        assert calls["n"] == 2

    def test_registry_does_not_retry_high_risk_tool(self):
        calls = {"n": 0}

        def flaky(_args):
            calls["n"] += 1
            raise _transient()

        reg = ToolRegistry()
        # Register under a high-risk name; the registry still converts the
        # surfaced exception to an ERROR string, but only after ONE attempt.
        reg.register(Tool(name="shell", description="d",
                          input_schema={"type": "object", "properties": {}},
                          fn=flaky))
        out = asyncio.run(reg.run("shell", {}))
        assert out.startswith("ERROR:")
        assert calls["n"] == 1
