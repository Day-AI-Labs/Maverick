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
    # The shipped first-party skills library lives INSIDE the package, so unlike
    # the user skills dir it is not isolated by HOME. Disable it by default so
    # the suite sees only the (empty, isolated) user dir -- behaviour unchanged
    # from before the library shipped. Tests opt in with MAVERICK_BUILTIN_SKILLS=1.
    monkeypatch.setenv("MAVERICK_BUILTIN_SKILLS", "0")
    # Pin the legacy (pre-secure-default) posture so the suite keeps asserting
    # each control's explicit on/off mechanics; the secure DEFAULT is covered by
    # test_secure_defaults.py (which overrides this). Production ships secure.
    monkeypatch.setenv("MAVERICK_SECURE_DEFAULT", "0")
    return tmp_path


@pytest.fixture(autouse=True)
def _isolate_root_logging():
    """Snapshot + restore the root logger around every test.

    ``maverick.cli`` configures process-global logging on every command run
    (the group callback calls ``_configure_cli_logging`` -> ``configure_logging``,
    which is idempotent and *replaces* the root handlers, optionally attaching a
    warning filter). Any ``CliRunner(main)`` test therefore mutates the root
    logger for the rest of the session -- removing pytest's caplog handler and
    leaving a filter that drops non-allowlisted WARNINGs -- which silently
    breaks later ``caplog``-based warning assertions. Resetting per test keeps
    that mutation from leaking; within a test logging still behaves normally.
    """
    import logging

    import maverick.logging_config as lc
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_filters = root.filters[:]
    saved_configured = getattr(lc, "_configured", False)
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        root.filters[:] = saved_filters
        lc._configured = saved_configured


@pytest.fixture(autouse=True)
def _reset_client_binding_cache():
    """Reset the process-global client-id floor + per-tenant DEK cache per test.

    ``client._cached`` floors ``current_tenant_id()`` for the WHOLE process, so
    a test that sets ``MAVERICK_CLIENT_ID``/``[client] id`` and calls
    ``client_id()`` leaves the cache populated: ``monkeypatch.setenv`` undoes the
    env at teardown but NOT the cache, so the next test in the same worker would
    silently re-home every ``data_dir()`` under ``tenants/<that-client>/``. Reset
    before and after each test so binding never leaks across tests. The DEK cache
    is keyed on the same (floored) tenant id, so clear it in lockstep.
    """
    def _reset():
        try:
            from maverick import client
            client.reset_client_cache()
        except Exception:
            pass
        try:
            from maverick.tenant import kms as tenant_kms
            tenant_kms._clear_cache()
        except Exception:
            pass
        try:
            from maverick import config
            config.reset_config_cache()
        except Exception:
            pass

    _reset()
    yield
    _reset()


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
        tools: list[dict] | None = None,
        budget=None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
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
        tools: list[dict] | None = None,
        budget=None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
        on_delta=None,
    ) -> LLMResponse:
        self._record(
            system=system, messages=messages, tools=tools,
            max_tokens=max_tokens, model=model,
        )
        return self._next()


def make_response(
    text: str = "",
    tool_calls: list[ToolCall] | None = None,
    thinking: str | None = None,
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
