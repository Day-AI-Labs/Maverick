"""P0 capability layer: host resource-scope enforcement at the tool chokepoint.

A capability whose ``allow_hosts`` is non-empty restricts which network hosts
the known network tools (http_fetch/browser/oidc) may reach: the host is parsed from
the tool's URL argument and denied if it matches no ``allow_hosts`` glob.
Default-open: an empty ``allow_hosts`` (the common case, and the only state
reachable without opting into capability enforcement) is a no-op, so normal
behaviour is unchanged.

Mirrors ``tests/test_capability_path_enforcement.py``'s ``_agent(tmp_path)`` +
``_run_tool`` setup; hermetic (no real LLM, no network).
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


def _spy_tool(name: str, calls: list, url_key: str = "url") -> Tool:
    """A fake network-shaped tool that records its calls instead of hitting net."""
    return Tool(
        name=name,
        description="spy",
        fn=lambda args: calls.append(args.get(url_key)) or "ran",
        input_schema={
            "type": "object",
            "properties": {url_key: {"type": "string"}},
        },
    )


@pytest.mark.asyncio
async def test_host_outside_scope_denied_and_tool_not_run(tmp_path):
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_hosts=frozenset({"*.example.com"}))
    calls: list = []
    # Register a fake http_fetch so a permitted call would be observable; the
    # denied call must NOT reach it.
    agent.tools.register(_spy_tool("http_fetch", calls))

    out = await agent._run_tool("http_fetch", {"url": "https://evil.com/x"})
    assert "DENIED by capability" in out
    assert "agent:coder-1" in out
    assert "evil.com" in out
    assert calls == []  # the network tool did not run


@pytest.mark.asyncio
async def test_oidc_token_url_outside_scope_denied_and_tool_not_run(tmp_path):
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_hosts=frozenset({"*.example.com"}))
    calls: list = []
    agent.tools.register(_spy_tool("oidc", calls, url_key="token_url"))

    out = await agent._run_tool("oidc", {"token_url": "https://evil.com/token"})
    assert "DENIED by capability" in out
    assert "evil.com" in out
    assert calls == []


@pytest.mark.asyncio
async def test_host_inside_scope_permitted(tmp_path):
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_hosts=frozenset({"*.example.com"}))
    calls: list = []
    agent.tools.register(_spy_tool("http_fetch", calls))

    out = await agent._run_tool("http_fetch", {"url": "https://api.example.com/x"})
    assert "DENIED" not in out
    assert calls == ["https://api.example.com/x"]  # passed the gate and ran


@pytest.mark.asyncio
async def test_tool_not_in_map_never_host_denied(tmp_path):
    # A tool with a `url` arg that is NOT a known network tool must never be
    # host-denied, even when the host is outside the scope.
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_hosts=frozenset({"*.example.com"}))
    calls: list = []
    agent.tools.register(_spy_tool("not_a_net_tool", calls))

    out = await agent._run_tool("not_a_net_tool", {"url": "https://evil.com/x"})
    assert "DENIED" not in out
    assert calls == ["https://evil.com/x"]


@pytest.mark.asyncio
async def test_no_allow_hosts_is_no_host_denial(tmp_path):
    # Default grant (empty allow_hosts == all): no host denial.
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1")  # no allow_hosts
    calls: list = []
    agent.tools.register(_spy_tool("http_fetch", calls))

    out = await agent._run_tool("http_fetch", {"url": "https://evil.com/x"})
    assert "DENIED" not in out
    assert calls == ["https://evil.com/x"]


@pytest.mark.asyncio
async def test_unrestricted_capability_none_is_no_host_denial(tmp_path):
    # capability is None == enforcement off entirely.
    agent = _agent(tmp_path)
    agent.capability = None
    calls: list = []
    agent.tools.register(_spy_tool("http_fetch", calls))

    out = await agent._run_tool("http_fetch", {"url": "https://evil.com/x"})
    assert "DENIED" not in out
    assert calls == ["https://evil.com/x"]


@pytest.mark.asyncio
async def test_missing_url_arg_fails_soft(tmp_path):
    # Fail-soft: a network tool called without its url arg must not crash on the
    # host check -- it falls through to the tool's own validation.
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_hosts=frozenset({"*.example.com"}))
    calls: list = []
    agent.tools.register(_spy_tool("http_fetch", calls))

    out = await agent._run_tool("http_fetch", {})  # no "url"
    assert "DENIED by capability" not in out
    assert calls == [None]  # reached the tool


@pytest.mark.asyncio
async def test_malformed_url_fails_soft(tmp_path):
    # Fail-soft: a URL with no parseable host (relative path) must not be
    # denied and must not crash -- the check is skipped and the tool runs.
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_hosts=frozenset({"*.example.com"}))
    calls: list = []
    agent.tools.register(_spy_tool("http_fetch", calls))

    out = await agent._run_tool("http_fetch", {"url": "not a url"})
    assert "DENIED by capability" not in out
    assert calls == ["not a url"]  # reached the tool


@pytest.mark.asyncio
async def test_url_that_raises_on_parse_fails_soft(tmp_path):
    # Fail-soft: a URL that makes urlsplit() raise (bad IPv6 literal) must not
    # crash the gate -- the check is skipped and the tool runs.
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_hosts=frozenset({"*.example.com"}))
    calls: list = []
    agent.tools.register(_spy_tool("http_fetch", calls))

    out = await agent._run_tool("http_fetch", {"url": "http://[::1"})
    assert "DENIED by capability" not in out
    assert calls == ["http://[::1"]  # reached the tool


@pytest.mark.asyncio
async def test_host_denial_is_audited(tmp_path, monkeypatch):
    import maverick.audit
    from maverick.audit import EventKind
    calls = []
    monkeypatch.setattr(maverick.audit, "record",
                        lambda kind, **kw: calls.append((kind, kw)) or True)
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_hosts=frozenset({"*.example.com"}))
    await agent._run_tool("browser",
                          {"action": "navigate", "url": "https://evil.com/x"})
    denied = [kw for k, kw in calls if k == EventKind.CAPABILITY_DENIED]
    assert denied, "host denial was not written to the audit log"
    assert denied[0]["tool"] == "browser"
    assert denied[0]["principal"] == "agent:coder-1"
    assert denied[0]["host"] == "evil.com"


@pytest.mark.asyncio
async def test_browser_receives_active_host_scope(tmp_path):
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_hosts=frozenset({"*.example.com"}))
    calls: list = []
    agent.tools.register(Tool(
        name="browser",
        description="spy browser",
        fn=lambda args: calls.append(args) or "ran",
        input_schema={"type": "object", "properties": {"url": {"type": "string"}}},
    ))

    out = await agent._run_tool("browser", {
        "action": "navigate",
        "url": "https://api.example.com/x",
    })
    assert "DENIED" not in out
    assert calls[0]["_capability_allow_hosts"] == ("*.example.com",)
