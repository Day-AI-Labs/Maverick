"""Blocking (Pre*) hooks are a guardrail: a TIMEOUT must fail CLOSED (a
large/slow tool arg could otherwise trip the deadline to bypass the guard),
and hooks must not be handed the kernel's secret env. Hook *bugs* (exceptions)
and missing binaries stay fail-open per the module's isolation contract.
"""
import sys

import pytest
from maverick import hooks
from maverick.hooks import HookContext, HookEvent


@pytest.fixture(autouse=True)
def _clean_registry():
    hooks.clear()
    yield
    hooks.clear()


async def _dispatch(event, **fields):
    return await hooks.dispatch(HookContext(event=event, **fields))


@pytest.mark.asyncio
async def test_blocking_hook_times_out_fails_closed():
    # A PreToolUse hook that sleeps past its timeout must BLOCK the action.
    hooks.register(
        HookEvent.PRE_TOOL_USE,
        f"{sys.executable} -c 'import time; time.sleep(5)'",
        matcher="*", timeout_ms=100,
    )
    allowed = await _dispatch(HookEvent.PRE_TOOL_USE, tool_name="shell")
    assert allowed is False


@pytest.mark.asyncio
async def test_post_hook_timeout_stays_fail_open():
    # PostToolUse can't block; a slow one must not wedge the run.
    import sys
    hooks.register(
        HookEvent.POST_TOOL_USE,
        f"{sys.executable} -c 'import time; time.sleep(5)'",
        matcher="*", timeout_ms=100,
    )
    allowed = await _dispatch(HookEvent.POST_TOOL_USE, tool_name="write_file")
    assert allowed is True


@pytest.mark.asyncio
async def test_blocking_missing_binary_stays_fail_open():
    # Missing binary is operator misconfig, not the attacker-triggerable
    # bypass; per the module contract it's logged and does not block.
    hooks.register(
        HookEvent.PRE_TOOL_USE, "/nonexistent/guardrail", matcher="*",
    )
    allowed = await _dispatch(HookEvent.PRE_TOOL_USE, tool_name="shell")
    assert allowed is True


@pytest.mark.asyncio
async def test_hook_env_omits_secrets(tmp_path, monkeypatch):
    # A hook must not receive the kernel's provider keys / tokens.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    monkeypatch.setenv("SOME_API_TOKEN", "tok-should-not-leak")
    monkeypatch.setenv("PLAIN_SETTING", "keep-me")
    out = tmp_path / "env.txt"
    script = tmp_path / "dump.sh"
    script.write_text(
        "#!/bin/sh\n"
        f"env > {out}\n"
        "exit 0\n"
    )
    script.chmod(0o755)
    hooks.register(HookEvent.POST_TOOL_USE, f"sh {script}", matcher="*", timeout_ms=5000)
    await _dispatch(HookEvent.POST_TOOL_USE, tool_name="x")
    dumped = out.read_text()
    assert "sk-ant-should-not-leak" not in dumped
    assert "tok-should-not-leak" not in dumped
    # Non-secret vars + the hook metadata still pass through.
    assert "keep-me" in dumped
    assert "MAVERICK_HOOK_EVENT=PostToolUse" in dumped
