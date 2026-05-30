"""Shared test fixtures for maverick-core.

Provides:
  - ``fake_llm``: a scripted ``FakeLLM`` instance that replaces ``maverick.llm.LLM``
    in tests. Push ``LLMResponse`` objects to ``scripted`` and the agent loop
    pops them in order. Recorded calls available on ``.calls`` for assertions.
  - ``make_llm_response``: helper to build LLMResponse fixtures quickly.

Using this pattern is the only way to test the recursive agent loop and the
OpenAI translator without burning API credits in CI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from maverick.llm import LLMResponse, ToolCall  # noqa: F401 - re-exported for tests


@pytest.fixture(autouse=True)
def _isolate_maverick_home(tmp_path, monkeypatch):
    """Point user-home resolution at a per-test temp dir on every platform.

    maverick resolves ``~/.maverick`` via ``Path.home()`` in ~30 places. On
    Windows ``Path.home()`` reads ``USERPROFILE`` and ignores the ``$HOME``
    that tests monkeypatch, so the suite (a) read the developer's REAL home
    (PermissionError on pre-existing world-readable files) and (b) WROTE fake
    sessions/config into the real ``~/.maverick`` (cross-run pollution — a
    leftover ``____evil`` session proved it). Set both ``HOME`` and the Windows
    vars so ``Path.home()`` is isolated everywhere.

    POSIX: this just sets ``HOME`` to a temp dir (what tests already do), so it
    is effectively a no-op and cannot regress Linux CI; a test that sets its own
    ``HOME`` still overrides this.
    """
    # Use tmp_path itself (not a subdir) so a test that sets HOME=tmp_path and
    # then computes tmp_path/.maverick/... lines up with Path.home() on every
    # platform (on Windows Path.home() reads USERPROFILE, set here too).
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows: what Path.home() reads
    return tmp_path


@dataclass
class FakeLLM:
    """Drop-in replacement for ``maverick.llm.LLM`` driven by a script."""

    scripted: list[LLMResponse] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    model: str = "fake:test"

    def _record(self, **kwargs) -> None:
        self.calls.append(kwargs)

    def _next(self) -> LLMResponse:
        if not self.scripted:
            return LLMResponse(
                text="FINAL: (script exhausted)",
                thinking=None,
                tool_calls=[],
                stop_reason="end_turn",
            )
        return self.scripted.pop(0)

    async def complete_async(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        budget=None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        self._record(
            system=system, messages=messages, tools=tools,
            max_tokens=max_tokens, model=model,
        )
        return self._next()

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        budget=None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
        on_delta=None,
    ) -> LLMResponse:
        self._record(
            system=system, messages=messages, tools=tools,
            max_tokens=max_tokens, model=model,
        )
        return self._next()


def make_response(
    text: str = "",
    tool_calls: Optional[list[ToolCall]] = None,
    thinking: Optional[str] = None,
    stop_reason: str = "end_turn",
) -> LLMResponse:
    return LLMResponse(
        text=text,
        thinking=thinking,
        tool_calls=tool_calls or [],
        stop_reason=stop_reason,
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def make_llm_response():
    return make_response
