"""Tool registry. Sync + async tools; same interface.

Each tool is a name + JSON schema + executor function. The executor may be a
sync function returning str, or an async coroutine returning str.

v0.1.2: ``base_registry`` accepts an optional list of MCPClient
instances. If provided, every tool the MCP servers expose is
registered as ``mcp_<server>__<tool>`` and routed through the
MCPClient. This is how Maverick consumes the wider MCP ecosystem.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Union

ToolFn = Callable[[dict[str, Any]], Union[str, Awaitable[str]]]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: ToolFn

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._acl_allowed: set[str] = set()
        self._acl_denied: set[str] = set()

    def set_acl(self, *, allowed: set[str] | None = None, denied: set[str] | None = None) -> None:
        self._acl_allowed = set(allowed or set())
        self._acl_denied = set(denied or set())

    def _acl_allows(self, name: str) -> bool:
        if self._acl_allowed and name not in self._acl_allowed:
            return False
        if self._acl_denied and name in self._acl_denied:
            return False
        return True

    def register(self, tool: Tool) -> None:
        if not self._acl_allows(tool.name):
            return
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def to_anthropic(self) -> list[dict[str, Any]]:
        return [t.to_anthropic() for t in self._tools.values()]

    async def run(self, name: str, args: dict[str, Any]) -> str:
        if name not in self._tools:
            return f"ERROR: unknown tool {name!r}"
        try:
            from ..observability import trace_span
        except ImportError:  # pragma: no cover
            import contextlib

            def trace_span(*a, **kw):  # type: ignore
                return contextlib.nullcontext()
        with trace_span("tool.run", attributes={"tool.name": name}):
            try:
                try:
                    from ..chaos import maybe_fail
                    maybe_fail("tool_dispatch",
                               message=f"chaos: tool_dispatch on {name!r}")
                except ImportError:
                    pass
                result = self._tools[name].fn(args)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception as e:
                return f"ERROR: {type(e).__name__}: {e}"


def base_registry(
    world,
    sandbox,
    mcp_clients: Optional[list] = None,
    goal_id: Optional[int] = None,
    enable_computer_use: bool = False,
    enable_browser: bool = False,
    enable_web_search: bool = False,
    channel: Optional[str] = None,
    user_id: Optional[str] = None,
) -> ToolRegistry:
    """Build the base tool set (no spawn tools).

    If ``mcp_clients`` is given, each one's discovered tools are
    registered as ``mcp_<server>__<tool>``.

    ``goal_id`` scopes ``ask_user`` so questions are filed against the
    running goal — otherwise the orchestrator's ``open_questions(gid)``
    filter returns nothing and "PAUSED: 0 open question(s)" is shown
    even though the agent asked.

    ``enable_computer_use`` / ``enable_browser`` register optional
    high-impact tools. Both require optional extras
    (``maverick-agent[computer-use]`` / ``[browser]``); when missing
    the tool factories raise an actionable ImportError at registration
    time, NOT at tool-call time -- so a user who picks computer-use in
    the wizard discovers the missing dep immediately rather than after
    the first run.
    """
    from .ask_user import ask_user
    from .attachments import list_attachments_tool
    from .fs import list_dir, read_file, write_file
    from .repo_map import repo_map
    from .shell import shell
    from .str_edit import str_replace_editor

    reg = ToolRegistry()
    # SSHBackend executes shell commands remotely, but filesystem tools
    # are local pathlib operations. Registering read/write/list for SSH
    # would access the Maverick host filesystem instead of the remote
    # sandbox host.
    if sandbox.__class__.__name__ != "SSHBackend":
        reg.register(read_file(sandbox))
        reg.register(write_file(sandbox))
        reg.register(list_dir(sandbox))
    reg.register(shell(sandbox))
    reg.register(ask_user(world, goal_id=goal_id))
    reg.register(list_attachments_tool(world, goal_id))
    reg.register(repo_map(sandbox))
    # Wave 10 (B1): surgical exact-match editor. OpenHands' biggest
    # single contribution to SWE-bench scores — eliminates ~30% of
    # apply-fail failures by side-stepping hand-authored diffs.
    reg.register(str_replace_editor(sandbox))

    from .recall import recall
    from .http_fetch import http_fetch
    from .pdf_reader import read_pdf
    from .view_image import view_image
    from .dep_graph import dep_graph
    from .ast_edit import ast_edit
    from .clipboard import clipboard
    from .preview_diff import preview_diff
    from .kv_memory import kv_memory
    from .a11y import a11y
    from .android import android
    from .apply_patch import apply_patch
    from .arxiv import arxiv
    from .calendar_tool import calendar_tool
    from .compute import compute
    from .currency import currency
    from .diagnose import diagnose
    from .discord_bot import discord_bot
    from .dns_lookup import dns_lookup
    from .email_tool import email_tool
    from .embeddings import embeddings
    from .file_watcher import file_watcher
    from .geocode import geocode
    from .git_advanced import git_advanced
    from .gitlab import gitlab
    from .hackernews import hackernews
    from .huggingface import huggingface
    from .ios_sim import ios_sim
    from .jira import jira
    from .mongodb_tool import mongodb_tool
    from .linear import linear
    from .notify import notify_tool
    from .notion import notion
    from .ocr import ocr
    from .openapi_runner import openapi_runner
    from .pandas_query import pandas_query
    from .posthog_tool import posthog_tool
    from .redis_tool import redis_tool
    from .semantic_scholar import semantic_scholar
    from .sentry_tool import sentry_tool
    from .shopify_tool import shopify_tool
    from .slack_bot import slack_bot
    from .spend_report import spend_report
    from .stripe_tool import stripe_tool
    from .test_impact import test_impact
    from .translate import translate
    from .wikipedia import wikipedia
    from .youtube import youtube
    reg.register(recall())
    reg.register(http_fetch())
    reg.register(read_pdf())
    reg.register(view_image())
    reg.register(dep_graph(sandbox))
    reg.register(ast_edit(sandbox))
    reg.register(clipboard())
    reg.register(preview_diff(sandbox))
    reg.register(kv_memory(world, goal_id))
    reg.register(arxiv())
    reg.register(semantic_scholar())
    reg.register(wikipedia())
    reg.register(apply_patch(sandbox))
    reg.register(compute())
    reg.register(email_tool())
    reg.register(pandas_query())
    reg.register(git_advanced(sandbox))
    reg.register(calendar_tool())
    reg.register(file_watcher())
    reg.register(linear())
    reg.register(jira())
    reg.register(gitlab())
    reg.register(embeddings())
    reg.register(huggingface())
    reg.register(notify_tool())
    reg.register(diagnose())
    reg.register(android())
    reg.register(ios_sim())
    reg.register(spend_report())
    reg.register(test_impact())
    reg.register(youtube())
    reg.register(notion())
    reg.register(translate())
    reg.register(slack_bot())
    reg.register(stripe_tool())
    reg.register(currency())
    reg.register(a11y())
    reg.register(discord_bot())
    reg.register(hackernews())
    reg.register(dns_lookup())
    reg.register(geocode())
    reg.register(openapi_runner())
    reg.register(ocr())
    reg.register(posthog_tool())
    reg.register(shopify_tool())
    reg.register(mongodb_tool())
    reg.register(redis_tool())
    reg.register(sentry_tool())

    # Voice tools (opt-in extra; tool factories raise ImportError only
    # when called without the required API key OR SDK; registering is
    # cheap).
    from .voice import speak, transcribe_audio
    reg.register(transcribe_audio())
    reg.register(speak())

    if enable_web_search:
        from .web_search import web_search
        reg.register(web_search())

    if enable_computer_use:
        from .computer import computer
        reg.register(computer())

    if enable_browser:
        from .browser import browser
        reg.register(browser())

    # Apply allow/deny lists from ~/.maverick/config.toml [security].
    # Fail-soft: any error here is logged and the registry is left
    # untouched.
    try:
        from ..safety.tool_acl import apply_to_registry
        apply_to_registry(reg, channel=channel, user_id=user_id)
    except Exception as e:  # pragma: no cover
        import logging as _logging
        _logging.getLogger(__name__).warning("tool_acl: %s", e)

    if mcp_clients:
        from ..mcp_tools import tools_from_mcp
        for client in mcp_clients:
            for t in tools_from_mcp(client):
                reg.register(t)

    # Per-tool rate limits from ~/.maverick/config.toml [rate_limits].
    # Wrap AFTER MCP + before plugin tools so MCP-exposed tools (which
    # share the most-abused namespace, mcp_*) are covered; plugins
    # register below and pick up their own limits via a second pass.
    try:
        from ..safety.rate_limiter import apply_to_registry as _rl_apply
        _rl_apply(reg)
    except Exception as e:  # pragma: no cover
        import logging as _logging
        _logging.getLogger(__name__).warning("rate_limiter: %s", e)

    # Plugin tools registered via the `maverick.tools` entry point. Each
    # factory is called with no args and must return a Tool. A broken
    # plugin logs but never takes the swarm down.
    try:
        from ..plugins import discover_tools
        for name, factory in discover_tools():
            try:
                t = factory()
                reg.register(t)
            except Exception as e:  # pragma: no cover -- plugin failure
                import logging
                logging.getLogger(__name__).warning(
                    "plugin tool %s factory raised: %s", name, e
                )
    except Exception:  # pragma: no cover -- importlib quirks
        pass

    # Second rate-limit pass to cover plugin-registered tools. Earlier
    # pass already wrapped core + MCP tools; double-wrapping is avoided
    # because apply_to_registry walks the current dict snapshot.
    try:
        from ..safety.rate_limiter import apply_to_registry as _rl_apply
        _rl_apply(reg)
    except Exception:  # pragma: no cover
        pass

    return reg


default_registry = base_registry
