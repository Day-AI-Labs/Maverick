"""P0 capability layer: path resource-scope enforcement at the tool chokepoint.

A capability whose ``allow_paths`` is non-empty restricts which filesystem
paths the known file tools (read_file/write_file/list_dir/str_replace_editor/
ast_edit) may touch. Default-open: an empty ``allow_paths`` (the common case,
and the only state reachable without opting into capability enforcement) is a
no-op, so normal behaviour is unchanged.

Mirrors ``tests/test_capability.py``'s ``_agent(tmp_path)`` + ``_run_tool``
setup; hermetic (no real LLM, no network).
"""

import pytest
from maverick.capability import Capability
from maverick.tools import Tool


def _agent(tmp_path):
    from maverick.agent import Agent
    from maverick.blackboard import Blackboard
    from maverick.budget import Budget
    from maverick.sandbox import LocalBackend
    from maverick.swarm import SwarmContext
    from maverick.world_model import WorldModel

    world = WorldModel(tmp_path / "world.db")
    goal_id = world.create_goal("g", "")
    ctx = SwarmContext(
        llm=None, world=world, budget=Budget(max_dollars=1.0),
        blackboard=Blackboard(), sandbox=LocalBackend(workdir=tmp_path),
        goal_id=goal_id, use_skills=False,
    )
    return Agent(ctx=ctx, role="coder", brief="b")


def _spy_tool(name: str, calls: list, path_key: str = "path") -> Tool:
    """A fake file-shaped tool that records its calls instead of touching FS."""
    return Tool(
        name=name,
        description="spy",
        fn=lambda args: calls.append(args.get(path_key)) or "ran",
        input_schema={
            "type": "object",
            "properties": {path_key: {"type": "string"}},
        },
    )


@pytest.mark.asyncio
async def test_path_outside_scope_denied_and_tool_not_run(tmp_path):
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_paths=frozenset({"/repo/*"}))
    calls: list = []
    # Register a fake read_file so a permitted call would be observable; the
    # denied call must NOT reach it.
    agent.tools.register(_spy_tool("read_file", calls))

    out = await agent._run_tool("read_file", {"path": "/etc/passwd"})
    assert "DENIED by capability" in out
    assert "agent:coder-1" in out
    assert "/etc/passwd" in out
    assert calls == []  # the file tool did not run


@pytest.mark.asyncio
async def test_path_inside_scope_permitted(tmp_path):
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_paths=frozenset({"/repo/*"}))
    calls: list = []
    agent.tools.register(_spy_tool("read_file", calls))

    out = await agent._run_tool("read_file", {"path": "/repo/ok.py"})
    assert "DENIED" not in out
    assert calls == ["/repo/ok.py"]  # passed the gate and ran


@pytest.mark.asyncio
async def test_tool_not_in_map_never_path_denied(tmp_path):
    # A tool with a `path` arg that is NOT a known file tool must never be
    # path-denied, even when the path is outside the scope.
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_paths=frozenset({"/repo/*"}))
    calls: list = []
    agent.tools.register(_spy_tool("not_a_file_tool", calls))

    out = await agent._run_tool("not_a_file_tool", {"path": "/etc/passwd"})
    assert "DENIED" not in out
    assert calls == ["/etc/passwd"]


@pytest.mark.asyncio
async def test_no_allow_paths_is_no_path_denial(tmp_path):
    # Default grant (empty allow_paths == all): no path denial.
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1")  # no allow_paths
    calls: list = []
    agent.tools.register(_spy_tool("read_file", calls))

    out = await agent._run_tool("read_file", {"path": "/etc/passwd"})
    assert "DENIED" not in out
    assert calls == ["/etc/passwd"]


@pytest.mark.asyncio
async def test_unrestricted_capability_none_is_no_path_denial(tmp_path):
    # capability is None == enforcement off entirely.
    agent = _agent(tmp_path)
    agent.capability = None
    calls: list = []
    agent.tools.register(_spy_tool("read_file", calls))

    out = await agent._run_tool("read_file", {"path": "/etc/passwd"})
    assert "DENIED" not in out
    assert calls == ["/etc/passwd"]


@pytest.mark.asyncio
async def test_missing_path_arg_fails_soft(tmp_path):
    # Fail-soft: a file tool called without its path arg must not crash on the
    # path check -- it falls through to the tool's own validation.
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_paths=frozenset({"/repo/*"}))
    calls: list = []
    agent.tools.register(_spy_tool("read_file", calls))

    out = await agent._run_tool("read_file", {})  # no "path"
    assert "DENIED by capability" not in out
    assert calls == [None]  # reached the tool


@pytest.mark.asyncio
async def test_path_denial_is_audited(tmp_path, monkeypatch):
    import maverick.audit
    from maverick.audit import EventKind
    calls = []
    monkeypatch.setattr(maverick.audit, "record",
                        lambda kind, **kw: calls.append((kind, kw)) or True)
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_paths=frozenset({"/repo/*"}))
    await agent._run_tool("write_file", {"path": "/etc/evil", "content": "x"})
    denied = [kw for k, kw in calls if k == EventKind.CAPABILITY_DENIED]
    assert denied, "path denial was not written to the audit log"
    assert denied[0]["tool"] == "write_file"
    assert denied[0]["principal"] == "agent:coder-1"
    assert denied[0]["path"] == "/etc/evil"
