"""Tool registry. Sync + async tools; same interface.

Each tool is a name + JSON schema + executor function. The executor may be a
sync function returning str, or an async coroutine returning str.

v0.1.2: ``base_registry`` accepts an optional list of MCPClient
instances. If provided, every tool the MCP servers expose is
registered as ``mcp_<server>__<tool>`` and routed through the
MCPClient. This is how Maverick consumes the wider MCP ecosystem.
"""
from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def as_bool(value: Any) -> bool:
    """Strict confirm gate for destructive or costly tool ops.

    Only a real boolean ``True`` authorises a live action. ``bool("false")``
    is ``True`` in Python, so a stringy confirm (from a non-conforming MCP
    client or a loose LLM) must fail closed to a dry run rather than fire a
    refund / delete / send. Shared so every gated tool decides the same way.
    """
    return value is True


def scrub_child_env() -> dict[str, Any]:
    """Env for a tool subprocess with secrets stripped.

    Tools that shell out (git/ffmpeg/pandoc/tesseract/adb/...) have no need
    for provider keys or connector tokens; inheriting the full ``os.environ``
    let a prompt-injected agent (or a hostile input file / repo config) read
    them out of the child. Reuse the sandbox's deny-by-pattern scrubber so a
    newly added credential is covered by default.
    """
    from ..sandbox.local import scrub_env
    return scrub_env()


# Media-tool flags that turn "convert a file" into arbitrary code exec or
# arbitrary file/URL read when injected via a freeform args[] array.
_DANGEROUS_MEDIA_FLAGS = (
    "-i", "--input", "-f", "--from", "--lua-filter", "--filter",
    "-lavfi", "-filter_complex", "-vf", "-af", "concat:",
    "--include-in-header", "--include-before-body", "--include-after-body",
    "--template", "--metadata-file", "--resource-path", "--extract-media",
    "--pdf-engine", "--syntax-definition", "--abbreviations", "--data-dir",
)


def safe_media_args(raw: Any) -> list[str]:
    """Filter a model-supplied freeform args[] list for media tools.

    By default DROP dangerous flags (input/filter/template injection that
    bypasses the tool's path confinement -- e.g. ``pandoc --lua-filter=x.lua``
    = arbitrary code, ``ffmpeg -i /etc/passwd`` = arbitrary file read). An
    operator who genuinely needs raw passthrough can opt in with
    ``MAVERICK_ALLOW_RAW_MEDIA_ARGS=1`` (then the list passes verbatim).
    """
    items = [str(a) for a in (raw or [])]
    if _env_true("MAVERICK_ALLOW_RAW_MEDIA_ARGS"):
        return items
    safe: list[str] = []
    skip_next = False
    for a in items:
        if skip_next:
            # This token is the value of a dropped flag (e.g. the path after
            # a bare `-i`); drop it too.
            skip_next = False
            continue
        low = a.lower()
        dangerous = False
        takes_value = False
        for f in _DANGEROUS_MEDIA_FLAGS:
            if f.endswith(":"):
                if low.startswith(f):          # e.g. concat:...
                    dangerous = True
                    break
            elif low == f:                     # bare flag -> value is the next token
                dangerous = True
                takes_value = True
                break
            elif low.startswith(f + "="):      # flag=value -> self-contained
                dangerous = True
                break
        if dangerous:
            skip_next = takes_value
            continue
        safe.append(a)
    return safe


def sandbox_run(
    sandbox: Any,
    argv: list[str],
    *,
    timeout: float = 120.0,
    stdin: str | None = None,
) -> tuple[int, str, str]:
    """Run ``argv`` through the sandbox chokepoint; return (code, stdout, stderr).

    Media tools (ffmpeg/imagemagick/pandoc/tesseract/pa11y...) historically
    shelled out on the host with ``subprocess.run`` even when a sandbox was
    wired in, bypassing the chokepoint that confines model-driven commands and
    lets tests swap the backend (CLAUDE.md rule #4). This routes the command
    through ``sandbox.exec()`` instead.

    Through a sandbox, the argv is shell-quoted with ``shlex.join`` and handed
    to ``exec()`` (which runs ``sh -c``); ``stdin`` is fed via a base64 pipe so
    arbitrary text reaches the process without shell-quoting hazards. When no
    sandbox is wired in, falls back to a scrubbed-env ``subprocess.run`` of the
    raw argv list (no shell interpolation -- the chokepoint guard forbids that
    outside the sandbox backends), passing ``stdin`` directly.
    """
    if sandbox is not None and hasattr(sandbox, "exec"):
        import shlex
        cmd = shlex.join(argv)
        if stdin is not None:
            import base64
            b64 = base64.b64encode(stdin.encode("utf-8")).decode("ascii")
            cmd = f"printf %s {shlex.quote(b64)} | base64 -d | {cmd}"
        try:
            res = sandbox.exec(cmd, timeout=timeout)
        except TypeError:
            # Backend without a per-call timeout kwarg.
            res = sandbox.exec(cmd)
        return res.exit_code, res.stdout, res.stderr

    import subprocess
    try:
        r = subprocess.run(
            argv, capture_output=True, text=True,
            timeout=timeout, env=scrub_child_env(), input=stdin,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"TIMEOUT after {timeout}s"


def host_exec(
    argv: list[str],
    *,
    timeout: float = 60.0,
    text: bool = True,
) -> tuple[int, Any, Any]:
    """Run ``argv`` directly on the HOST, deliberately NOT sandbox-mediated.

    CLAUDE.md rule #4 ("sandbox-mediate all shell") applies to *model-influenced
    commands whose work happens inside the workspace* — those go through
    ``sandbox_run`` / ``sandbox.exec`` so the configured container isolation
    applies and tests can swap the backend.

    A small set of tools are **host-bound by nature**: the resource they act on
    (a USB-attached Android device via ``adb``, an iOS simulator via ``simctl``,
    the desktop clipboard) lives on the *host*, not in the workspace. The
    sandbox runs in a network-isolated container with no access to that
    hardware, so routing these through ``sandbox.exec`` would simply break them.
    They call ``host_exec`` instead — a single, greppable, env-scrubbed entry
    point that makes the "intentionally direct, not sandbox-mediated" choice
    explicit and auditable (rather than a bare ``subprocess.run`` that looks
    like an un-migrated rule-#4 violation).

    Returns ``(exit_code, stdout, stderr)``; a timeout yields ``(124, "", msg)``.
    The child env is scrubbed of secrets (``scrub_child_env``). ``argv`` is a
    list (no shell interpolation).
    """
    import subprocess
    try:
        r = subprocess.run(
            argv, capture_output=True, text=text,
            timeout=timeout, env=scrub_child_env(),
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        empty = "" if text else b""
        return 124, empty, f"TIMEOUT after {timeout}s"


def _forward_chunk(listener, name: str, chunk: Any) -> str:
    """Streaming tool_result: forward one chunk to the registry listener
    (best-effort) and return it as text for accumulation."""
    piece = chunk if isinstance(chunk, str) else str(chunk)
    if listener is not None:
        try:
            listener(name, piece)
        except Exception:  # listener must never break the call
            pass
    return piece


async def _execute_tool_fn(fn, args: dict[str, Any], stream_chunk) -> str:
    """Run a tool fn under every supported contract.

    str-returning (sync or async) is the classic contract. **Streaming
    tool_result**: a fn may be an async generator, or return a sync
    generator/iterator of chunks — chunks flow through ``stream_chunk`` as
    they are produced (the dashboard/TUI live-view seam) and the joined text
    is the tool_result the model sees, so the model protocol is unchanged.
    Sync fns (and sync generators) drain on a worker thread so a slow tool
    can't stall the event loop.
    """
    if inspect.iscoroutinefunction(fn):
        out = await fn(args)
    elif inspect.isasyncgenfunction(fn):
        parts: list[str] = []
        async for chunk in fn(args):
            parts.append(stream_chunk(chunk))
        return "".join(parts)
    else:
        out = await asyncio.to_thread(fn, args)
    if inspect.isawaitable(out):
        out = await out
    if inspect.isgenerator(out) or (hasattr(out, "__next__") and not isinstance(out, str)):
        parts = []

        def _drain() -> None:
            for chunk in out:
                parts.append(stream_chunk(chunk))

        await asyncio.to_thread(_drain)
        return "".join(parts)
    return out


ToolFn = Callable[[dict[str, Any]], str | Awaitable[str]]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: ToolFn
    # When True, the agent loop may run this tool CONCURRENTLY with the
    # other tool calls in the same model turn (asyncio.gather). Only set
    # it on side-effect-free, idempotent reads (read_file, list_dir,
    # repo_map, dep_graph). Anything that writes the workspace, shells
    # out, spawns children, sends a message, or holds a remote rate limit
    # must stay False so it executes serially. The loop only parallelises
    # a turn when EVERY call in it is parallel_safe, so the default of
    # False is always safe — it just forgoes the speedup. Not part of
    # ``to_anthropic()``: it must never alter the tool catalog the model
    # sees (that would bust the prompt cache).
    parallel_safe: bool = False

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    # Deferred-loading meta-tool name (see enable_deferred / find_tools.py).
    META_TOOL = "find_tools"

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._acl_allowed: set[str] = set()
        self._acl_denied: set[str] = set()
        self._acl_max_risk: str | None = None
        # Deferred tool loading: when on, only _core (+ find_tools + any
        # _activated) tools are shown to the model; the long tail is
        # discovered on demand. run() can still execute ANY registered tool.
        self._deferred = False
        self._core_names: set[str] = set()
        self._core: set[str] = set()
        self._activated: set[str] = set()
        # Streaming tool_result: an optional listener that receives
        # (tool_name, chunk) for tools whose fn yields chunks (generators).
        # The model still gets the joined result; this is the live-UX seam.
        self._chunk_listener = None
        # Memoized to_anthropic() payload. The exposed tool set is stable
        # across turns (it only changes on register / set_acl /
        # enable_deferred / activate), but the agent loop re-serialises all
        # 80+ tool schemas every model turn. Cache it and invalidate at those
        # four mutation points. Consumers copy before mutating (the Anthropic
        # provider does ``[dict(t) for t in ...]``), so sharing is safe.
        self._anthropic_cache: list[dict[str, Any]] | None = None

    def set_acl(
        self,
        *,
        allowed: set[str] | None = None,
        denied: set[str] | None = None,
        max_risk: str | None = None,
    ) -> None:
        self._acl_allowed = set(allowed or set())
        self._acl_denied = set(denied or set())
        self._acl_max_risk = max_risk
        self._anthropic_cache = None

    def _acl_allows(self, name: str) -> bool:
        if self._acl_allowed and name not in self._acl_allowed:
            return False
        if self._acl_denied and name in self._acl_denied:
            return False
        if self._acl_max_risk:
            from ..safety.tool_risk import risk_rank, tool_risk

            if risk_rank(tool_risk(name)) > risk_rank(self._acl_max_risk):
                return False
        return True

    def set_chunk_listener(self, listener) -> None:
        """Register ``listener(tool_name, chunk)`` for streaming tool output.

        Tools that return an iterator/generator of str chunks stream through
        it as they produce output (dashboard/TUI live view); the joined text
        remains the tool_result the model sees. Pass None to clear. Listener
        errors are swallowed — observability must never break a tool call.
        """
        self._chunk_listener = listener

    def register(self, tool: Tool) -> None:
        if not self._acl_allows(tool.name):
            return
        self._tools[tool.name] = tool
        if self._deferred and tool.name in self._core_names:
            self._core.add(tool.name)
        self._anthropic_cache = None

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    # --- deferred tool loading -----------------------------------------
    # With 80+ tools (+ MCP servers), sending every schema every turn
    # dominates the context window. When enabled, only a small CORE set +
    # the find_tools meta-tool are exposed to the model; the long tail is
    # discovered and activated on demand. The exposed set is stable across
    # turns (until an activation), so the tool-catalog prompt cache still
    # hits. activation only governs what the model SEES -- run() executes
    # any registered tool regardless.

    def enable_deferred(self, core: set[str]) -> None:
        """Expose only ``core`` (∩ registered) + find_tools to the model."""
        self._deferred = True
        self._core_names = set(core)
        self._core = {n for n in self._core_names if n in self._tools}
        self._anthropic_cache = None

    def deferred_enabled(self) -> bool:
        return self._deferred

    def _exposed_names(self) -> set[str]:
        return self._core | self._activated | {self.META_TOOL}

    def activate(self, names: list[str]) -> list[str]:
        """Reveal deferred tools to the model. Returns the names that
        resolved to a registered tool (unknown names are ignored)."""
        resolved = [n for n in names if n in self._tools]
        if resolved:
            self._activated.update(resolved)
            self._anthropic_cache = None
        return resolved

    def exposed(self) -> list[Tool]:
        """Tools the model sees this turn, in registration order.

        Identity when deferred loading is off, so default behavior and the
        byte-identical tool catalog (for prompt caching) are unchanged.
        """
        if not self._deferred:
            return list(self._tools.values())
        names = self._exposed_names()
        return [t for n, t in self._tools.items() if n in names]

    def deferred_tools(self) -> list[Tool]:
        """Registered tools not currently exposed -- find_tools' search space."""
        names = self._exposed_names()
        return [t for n, t in self._tools.items() if n not in names]

    def to_anthropic(self) -> list[dict[str, Any]]:
        if self._anthropic_cache is None:
            self._anthropic_cache = [t.to_anthropic() for t in self.exposed()]
        return self._anthropic_cache

    async def run(self, name: str, args: dict[str, Any]) -> str:
        if name not in self._tools:
            return f"ERROR: unknown tool {name!r}"
        try:
            from ..observability import gen_ai_tool_attributes, trace_span
        except ImportError:  # pragma: no cover
            import contextlib

            def trace_span(*a, **kw):  # type: ignore
                return contextlib.nullcontext()

            def gen_ai_tool_attributes(tool_name, **kw):  # type: ignore
                return {}
        with trace_span(
            "tool.run",
            attributes={"tool.name": name, **gen_ai_tool_attributes(name)},
        ):
            import time as _perf_time
            _t0 = _perf_time.perf_counter()
            try:
                # Opt-in tool-output cache (default OFF): serve a memoized
                # result for side-effect-free (parallel_safe) tools so a
                # repeated read doesn't re-do the work. Never caches writes
                # or error results. See tool_cache.py.
                _tool = self._tools[name]
                try:
                    from ..tool_cache import get_cached, store_cached
                except ImportError:  # pragma: no cover
                    get_cached = store_cached = None  # type: ignore[assignment]
                if get_cached is not None:
                    _hit, _cached = get_cached(_tool, args)
                    if _hit:
                        try:
                            from ..observability import record_metric as _rm
                            _rm("tool_calls",
                                labels={"tool": name, "status": "cache"})
                        except Exception:  # pragma: no cover
                            pass
                        return _cached
                try:
                    from ..chaos import maybe_fail
                    maybe_fail("tool_dispatch",
                               message=f"chaos: tool_dispatch on {name!r}")
                except ImportError:
                    pass
                async def _invoke() -> str:
                    return await _execute_tool_fn(
                        self._tools[name].fn, args,
                        lambda chunk: _forward_chunk(self._chunk_listener, name, chunk),
                    )

                # One shared reliability policy: transient upstream failures
                # on retry-safe (non-high-risk) tools are retried with backoff.
                from ..tool_reliability import run_with_retry
                result = await run_with_retry(name, _invoke)
                if store_cached is not None:
                    try:
                        store_cached(_tool, args, result)
                    except Exception:  # pragma: no cover
                        pass
                try:
                    from ..observability import record_metric as _rm
                    _rm("tool_calls", labels={"tool": name, "status": "ok"})
                except Exception:  # pragma: no cover
                    pass
                return result
            except Exception as e:
                # Tool errors (incl. an injected tool_dispatch chaos failure)
                # are surfaced as a tool-result string so the agent can react
                # — this mirrors how real tool exceptions behave. The chaos
                # gap the council flagged is on the LLM path, fixed by wiring
                # maybe_fail("llm_call") into complete_async (not here).
                try:
                    from ..observability import record_metric as _rm
                    _rm("tool_calls", labels={"tool": name, "status": "error"})
                except Exception:  # pragma: no cover
                    pass
                return f"ERROR: {type(e).__name__}: {e}"
            finally:
                # Always-on per-tool latency profile (complements OTel spans).
                # Records on both the success and error paths; never raises.
                _elapsed_ms = (_perf_time.perf_counter() - _t0) * 1000.0
                try:
                    from ..tool_latency import record as _rec_latency
                    _rec_latency(name, _elapsed_ms)
                except Exception:  # pragma: no cover -- profiling never breaks a tool
                    pass
                # Opt-in per-tool latency budget (default OFF): record a breach
                # if the call ran longer than [tools] latency_budget_ms. Fail-open.
                try:
                    from ..latency_budget import note_elapsed as _note_budget
                    _note_budget(name, _elapsed_ms)
                except Exception:  # pragma: no cover -- budget never breaks a tool
                    pass


# Tools exposed to the model by default under deferred loading. The long
# tail (SaaS/cloud integrations, MCP, plugins) is discovered via find_tools.
# Listing a name that isn't registered is harmless -- enable_deferred
# intersects with the actual registry.
CORE_TOOL_NAMES = frozenset({
    # filesystem + execution
    "read_file", "write_file", "list_dir", "shell",
    # code editing
    "str_replace_editor", "apply_patch", "ast_edit", "preview_diff",
    # repo understanding
    "repo_map", "dep_graph",
    # interaction + attachments
    "ask_user", "list_attachments",
    # web / docs / media basics
    "http_fetch", "web_search", "read_pdf", "view_image",
    # memory + run introspection
    "recall_past_goals", "kv_memory", "memory", "budget_status", "diagnose",
    "spend_report", "notify", "compute",
    # multi-agent
    "spawn_subagent", "spawn_swarm",
})


def _deferred_loading_enabled() -> bool:
    """Whether deferred tool loading is on (default off -- unchanged behavior).

    Enable with ``MAVERICK_DEFERRED_TOOLS=1`` or ``[tools] deferred_loading =
    true`` in ``~/.maverick/config.toml``.
    """
    if _env_true("MAVERICK_DEFERRED_TOOLS"):
        return True
    try:
        from ..config import load_config
        return bool(load_config().get("tools", {}).get("deferred_loading", False))
    except Exception:  # pragma: no cover -- config never blocks the registry
        return False


def base_registry(  # noqa: C901
    world,
    sandbox,
    mcp_clients: list | None = None,
    goal_id: int | None = None,
    enable_computer_use: bool = False,
    enable_browser: bool = False,
    enable_web_search: bool = False,
    enable_mobile_tools: bool = False,
    channel: str | None = None,
    user_id: str | None = None,
    budget: Any = None,
) -> ToolRegistry:
    """Build the base tool set (no spawn tools).

    If ``mcp_clients`` is given, each one's discovered tools are
    registered as ``mcp_<server>__<tool>``.

    ``goal_id`` scopes ``ask_user`` so questions are filed against the
    running goal — otherwise the orchestrator's ``open_questions(gid)``
    filter returns nothing and "PAUSED: 0 open question(s)" is shown
    even though the agent asked.

    ``enable_computer_use`` / ``enable_browser`` / ``enable_mobile_tools``
    register optional high-impact tools. Computer/browser require
    optional extras
    (``maverick-agent[computer-use]`` / ``[browser]``); when missing
    the tool factories raise an actionable ImportError at registration
    time, NOT at tool-call time -- so a user who picks computer-use in
    the wizard discovers the missing dep immediately rather than after
    the first run.

    ``budget`` binds tools that perform their own metered provider calls
    (for example ``view_video``) to the active run budget.
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
        reg.register(write_file(sandbox, goal_id=goal_id))
        reg.register(list_dir(sandbox))
    reg.register(shell(sandbox))
    reg.register(ask_user(world, goal_id=goal_id))
    reg.register(list_attachments_tool(world, goal_id))
    reg.register(repo_map(sandbox))
    # Wave 10 (B1): surgical exact-match editor. OpenHands' biggest
    # single contribution to SWE-bench scores — eliminates ~30% of
    # apply-fail failures by side-stepping hand-authored diffs.
    reg.register(str_replace_editor(sandbox))

    from .a11y import a11y
    from .a11y_tree import a11y_tree
    from .adversarial_self_test import adversarial_self_test
    from .agent_simulator import agent_simulator
    from .ai_act_classifier import ai_act_classifier
    from .airtable_tool import airtable_tool
    from .android import android
    from .anki import anki
    from .apple_shortcuts import apple_shortcuts
    from .apply_patch import apply_patch
    from .arxiv import arxiv
    from .asana_tool import asana_tool
    from .ast_edit import ast_edit
    from .async_compaction import async_compaction
    from .audit_mirror import audit_mirror
    from .autogen_adapter import autogen_adapter
    from .bias_eval import bias_eval
    from .bitbucket_tool import bitbucket_tool
    from .budget_status import budget_status
    from .cache_admin import cache_admin
    from .cache_eviction import cache_eviction
    from .calendar_tool import calendar_tool
    from .calendly_tool import calendly_tool
    from .capability_delegation import capability_delegation
    from .capability_delegation_graph import capability_delegation_graph
    from .capability_leak_fuzzer import capability_leak_fuzzer
    from .capability_negotiation import capability_negotiation
    from .chaos_gameday import chaos_gameday
    from .citation_verifier import citation_verifier
    from .clickup_tool import clickup_tool
    from .clipboard import clipboard
    from .cloudflare_tool import cloudflare_tool
    from .collusion_detector import collusion_detector
    from .comparative_replay import comparative_replay
    from .compute import compute
    from .confluence_tool import confluence_tool
    from .constrained_output import constrained_output
    from .container_build import container_build
    from .containment_mode import containment_mode
    from .coordinated_disclosure import coordinated_disclosure
    from .cost_attribution import cost_attribution
    from .cost_aware_router import cost_aware_router
    from .cost_guardrail import cost_guardrail
    from .cost_of_quality import cost_of_quality
    from .crewai_adapter import crewai_adapter
    from .cross_repo_deps import cross_repo_deps
    from .crypto_budget_receipt import crypto_budget_receipt
    from .currency import currency
    from .data_residency import data_residency
    from .datadog_tool import datadog_tool
    from .decision_explainer import decision_explainer
    from .dep_graph import dep_graph
    from .diagnose import diagnose
    from .diff_to_expected import diff_to_expected
    from .differential_privacy import differential_privacy
    from .discord_bot import discord_bot
    from .discord_slash import discord_slash
    from .dns_lookup import dns_lookup
    from .dp_stats import dp_stats
    from .dropbox_tool import dropbox_tool
    from .dynamodb_tool import dynamodb_tool
    from .elasticsearch_tool import elasticsearch_tool
    from .email_tool import email_tool
    from .embeddings import embeddings
    from .energy_accounting import energy_accounting
    from .erp_tool import erp_tool
    from .error_patterns import error_patterns
    from .fairness_scheduler import fairness_scheduler
    from .ffmpeg_tool import ffmpeg_tool
    from .file_watcher import file_watcher
    from .ga4_tool import ga4_tool
    from .gdrive_tool import gdrive_tool
    from .generic_oauth import generic_oauth
    from .geocode import geocode
    from .geofence import geofence
    from .git_advanced import git_advanced
    from .github_actions import github_actions
    from .github_issues import github_issues
    from .github_repo_search import github_repo_search
    from .gitlab import gitlab
    from .gitlab_issues import gitlab_issues
    from .gmail_tool import gmail_tool
    from .hackernews import hackernews
    from .home_assistant_tool import home_assistant_tool
    from .honeytoken import honeytoken
    from .http_fetch import http_fetch
    from .hubspot_tool import hubspot_tool
    from .huggingface import huggingface
    from .imagemagick_tool import imagemagick_tool
    from .ios_sim import ios_sim
    from .jira import jira
    from .key_rotation import key_rotation
    from .knowledge_graph import knowledge_graph
    from .kv_memory import kv_memory
    from .lambda_tool import lambda_tool
    from .latency_heatmap import latency_heatmap
    from .latency_slo import latency_slo
    from .linear import linear
    from .local_embeddings_cache import local_embeddings_cache
    from .marketplace_ratings import marketplace_ratings
    from .memleak_quarantine import memleak_quarantine
    from .memory import memory
    from .migration_cost import migration_cost
    from .mixpanel_tool import mixpanel_tool
    from .model3d_inspect import model3d_inspect
    from .model_card import model_card
    from .mongodb_tool import mongodb_tool
    from .msgraph_tool import msgraph_tool
    from .multimodal_rag import multimodal_rag
    from .multiregion_failover import multiregion_failover
    from .mutation_test import mutation_test
    from .newsapi_tool import newsapi_tool
    from .notify import notify_tool
    from .notion import notion
    from .obsidian import obsidian
    from .ocr import ocr
    from .office_convert import office_convert
    from .openapi_runner import openapi_runner
    from .openmetrics import openmetrics
    from .outline_writer import outline_writer
    from .pagerduty_tool import pagerduty_tool
    from .pandas_query import pandas_query
    from .pandoc_tool import pandoc_tool
    from .pdf_reader import read_pdf
    from .pia_generator import pia_generator
    from .plaid_tool import plaid_tool
    from .plain_language import plain_language
    from .plausible_tool import plausible_tool
    from .plugin_lockfile import plugin_lockfile
    from .polyglot_injection import polyglot_injection
    from .posthog_tool import posthog_tool
    from .preview_diff import preview_diff
    from .privacy_budget import privacy_budget
    from .process_introspect import process_introspect
    from .provenance_chain import provenance_chain
    from .provider_failover_policy import provider_failover_policy
    from .query_plan_regression import query_plan_regression
    from .quorum_approval import quorum_approval
    from .recall import recall
    from .rectification import rectification
    from .reddit_tool import reddit_tool
    from .redis_tool import redis_tool
    from .reflect_loop import reflect_loop
    from .reliability_harness import reliability_harness
    from .replicate_tool import replicate_tool
    from .right_to_explanation import right_to_explanation
    from .risk_tier import risk_tier
    from .risk_tier_classifier import risk_tier_classifier
    from .run_events_firehose import run_events_firehose
    from .s3_attachments import s3_attachments
    from .s3_tool import s3_tool
    from .saas_trigger import saas_trigger
    from .saas_trigger_registry import saas_trigger_registry
    from .safety_regression_budget import safety_regression_budget
    from .salesforce_tool import salesforce_tool
    from .semantic_code_search import semantic_code_search
    from .semantic_scholar import semantic_scholar
    from .sentry_tool import sentry_tool
    from .ses_tool import ses_tool
    from .shopify_tool import shopify_tool
    from .sla_breach import sla_breach
    from .slack_bot import slack_bot
    from .slack_workflow import slack_workflow
    from .smart_goal_completion import smart_goal_completion
    from .smart_nl_filter import smart_nl_filter
    from .sns_tool import sns_tool
    from .spend_report import spend_report
    from .spotify_tool import spotify_tool
    from .spreadsheet import spreadsheet
    from .sql_query import sql_query
    from .streaming_reasoning_trace import streaming_reasoning_trace
    from .stripe_tool import stripe_tool
    from .supply_chain_pin import supply_chain_pin
    from .synthetic_data import synthetic_data
    from .template_generator import template_generator
    from .test_gen import test_gen
    from .test_impact import test_impact
    from .tiered_storage import tiered_storage
    from .tool_call_inspector import tool_call_inspector
    from .translate import translate
    from .trello_tool import trello_tool
    from .twilio_tool import twilio_tool
    from .two_person_rule import two_person_rule
    from .unified_inbox import unified_inbox
    from .vercel_tool import vercel_tool
    from .view_image import view_image
    from .view_video import view_video
    from .voice_cloning_consent import voice_cloning_consent
    from .wal_contention import wal_contention
    from .watermark_detector import watermark_detector
    from .web_archive import web_archive
    from .web_recorder import web_recorder
    from .whats_changed import whats_changed
    from .wikipedia import wikipedia
    from .wolfram_tool import wolfram_tool
    from .youtube import youtube
    from .zoom_tool import zoom_tool
    reg.register(recall())
    reg.register(http_fetch())
    from .control_tools import find_controls_tool
    reg.register(find_controls_tool())
    reg.register(read_pdf())
    reg.register(view_image())
    reg.register(view_video(sandbox, budget=budget))
    reg.register(dep_graph(sandbox))
    reg.register(ast_edit(sandbox))
    reg.register(clipboard())
    reg.register(preview_diff(sandbox))
    reg.register(kv_memory(world, goal_id))
    reg.register(memory())
    reg.register(arxiv())
    reg.register(semantic_scholar())
    reg.register(wikipedia())
    reg.register(apply_patch(sandbox))
    reg.register(compute())
    reg.register(sql_query(sandbox))
    reg.register(email_tool())
    reg.register(pandas_query(sandbox))
    reg.register(git_advanced(sandbox))
    reg.register(calendar_tool())
    reg.register(capability_delegation())
    reg.register(coordinated_disclosure())
    reg.register(collusion_detector())
    reg.register(risk_tier())
    reg.register(bias_eval())
    reg.register(decision_explainer())
    reg.register(rectification())
    reg.register(file_watcher(sandbox))
    reg.register(linear())
    reg.register(jira())
    reg.register(gitlab())
    reg.register(embeddings())
    reg.register(error_patterns())
    reg.register(huggingface())
    reg.register(notify_tool())
    reg.register(diagnose())
    reg.register(differential_privacy())
    if enable_mobile_tools:
        reg.register(android())
        reg.register(ios_sim())
    reg.register(spend_report())
    reg.register(budget_status(budget=budget))
    reg.register(test_impact())
    reg.register(youtube())
    reg.register(notion())
    reg.register(obsidian())
    reg.register(spreadsheet(sandbox))
    reg.register(translate())
    reg.register(slack_bot())
    reg.register(stripe_tool())
    from .sanctions_screen import sanctions_screen
    reg.register(sanctions_screen())  # finance: OFAC/SDN screening (finance-agent-suite)
    reg.register(currency())
    reg.register(a11y(sandbox))
    reg.register(discord_bot())
    reg.register(hackernews())
    reg.register(dns_lookup())
    reg.register(geocode())
    reg.register(geofence())
    reg.register(knowledge_graph())
    reg.register(citation_verifier())
    reg.register(cross_repo_deps(sandbox))
    reg.register(test_gen())
    reg.register(two_person_rule())
    reg.register(capability_delegation_graph())
    reg.register(honeytoken())
    reg.register(dp_stats())
    reg.register(cost_attribution())
    reg.register(model_card())
    reg.register(supply_chain_pin())
    reg.register(quorum_approval())
    reg.register(crypto_budget_receipt())
    reg.register(provenance_chain())
    reg.register(migration_cost())
    reg.register(energy_accounting())
    reg.register(cost_guardrail())
    reg.register(cache_eviction())
    reg.register(latency_slo())
    reg.register(cost_of_quality())
    reg.register(outline_writer())
    reg.register(agent_simulator())
    reg.register(fairness_scheduler())
    reg.register(process_introspect())
    reg.register(adversarial_self_test())
    reg.register(reflect_loop())
    reg.register(github_repo_search())
    reg.register(github_issues())
    reg.register(gitlab_issues())
    reg.register(web_archive())
    reg.register(anki())
    reg.register(s3_attachments())
    reg.register(template_generator())
    reg.register(generic_oauth())
    reg.register(plugin_lockfile())
    reg.register(saas_trigger())
    reg.register(apple_shortcuts())
    reg.register(discord_slash())
    reg.register(slack_workflow())
    reg.register(risk_tier_classifier())
    reg.register(containment_mode())
    reg.register(capability_leak_fuzzer())
    reg.register(right_to_explanation())
    reg.register(audit_mirror())
    reg.register(tiered_storage())
    reg.register(async_compaction())
    reg.register(wal_contention())
    reg.register(memleak_quarantine())
    reg.register(openmetrics())
    reg.register(sla_breach())
    reg.register(whats_changed())
    reg.register(comparative_replay())
    reg.register(tool_call_inspector())
    reg.register(latency_heatmap())
    reg.register(plain_language())
    reg.register(multimodal_rag())
    reg.register(query_plan_regression())
    reg.register(provider_failover_policy())
    reg.register(cost_aware_router())
    reg.register(multiregion_failover())
    reg.register(reliability_harness())
    reg.register(chaos_gameday())
    reg.register(pia_generator())
    reg.register(capability_negotiation())
    reg.register(key_rotation())
    reg.register(data_residency())
    reg.register(polyglot_injection())
    reg.register(safety_regression_budget())
    reg.register(autogen_adapter())
    reg.register(crewai_adapter())
    reg.register(run_events_firehose())
    reg.register(marketplace_ratings())
    reg.register(local_embeddings_cache())
    reg.register(saas_trigger_registry())
    reg.register(streaming_reasoning_trace())
    reg.register(voice_cloning_consent())
    reg.register(diff_to_expected())
    reg.register(smart_goal_completion())
    reg.register(unified_inbox())
    reg.register(smart_nl_filter())
    reg.register(semantic_code_search(sandbox))
    reg.register(mutation_test())
    reg.register(constrained_output())
    reg.register(model3d_inspect(sandbox))
    reg.register(synthetic_data())
    reg.register(web_recorder())
    reg.register(watermark_detector())
    from .agent_identity import agent_identity
    # capability_delegation_graph / collusion_detector / coordinated_disclosure:
    # registered once above (parallel-built on both branches; unified at merge).
    reg.register(agent_identity())
    from .adversarial_eval import adversarial_eval
    from .gui_element_memory import gui_element_memory
    from .voice_command_grammar import voice_command_grammar
    from .what_changed_digest import what_changed_digest
    reg.register(voice_command_grammar())
    reg.register(what_changed_digest())
    reg.register(gui_element_memory())
    reg.register(adversarial_eval())
    from .trace_compare import trace_compare
    # latency_heatmap / tool_call_inspector: registered once above (merge dup).
    reg.register(trace_compare())
    from .github_search import github_search
    from .governance_explainer import governance_explainer
    from .image_content_classifier import image_content_classifier
    from .lsp_bridge import lsp_bridge
    from .oauth_helper import oauth_helper
    # template_generator / web_archive / anki: registered once above
    # (parallel-built on both branches; unified at merge).
    reg.register(image_content_classifier())
    reg.register(lsp_bridge())
    reg.register(oauth_helper())
    reg.register(github_search())
    reg.register(governance_explainer())
    reg.register(a11y_tree())
    reg.register(ai_act_classifier())
    reg.register(cache_admin())
    reg.register(openapi_runner(sandbox))
    reg.register(ocr(sandbox))
    reg.register(container_build(sandbox))
    reg.register(posthog_tool())
    reg.register(privacy_budget())
    reg.register(shopify_tool())
    reg.register(mongodb_tool())
    reg.register(redis_tool())
    reg.register(sentry_tool())
    reg.register(pagerduty_tool())
    reg.register(salesforce_tool())
    reg.register(cloudflare_tool())
    reg.register(datadog_tool())
    reg.register(hubspot_tool())
    reg.register(twilio_tool())
    reg.register(s3_tool())
    reg.register(elasticsearch_tool())
    reg.register(github_actions())
    # Strategic-fit connectors (ITSM / data / cloud-ML / GRC). Explicit-token
    # auth (no ambient creds), so registered unconditionally like salesforce.
    from .bigquery_tool import bigquery_tool
    from .databricks_tool import databricks_tool
    from .dynamics_tool import dynamics_tool
    from .onetrust_tool import onetrust_tool
    from .oracle_tool import oracle_tool
    from .sap_tool import sap_tool
    from .servicenow_tool import servicenow_tool
    from .snowflake_tool import snowflake_tool
    from .vertex_tool import vertex_tool
    from .workday_tool import workday_tool
    reg.register(servicenow_tool())
    reg.register(snowflake_tool())
    reg.register(databricks_tool())
    reg.register(onetrust_tool())
    reg.register(vertex_tool())
    reg.register(oracle_tool())
    reg.register(sap_tool())
    reg.register(workday_tool())
    reg.register(bigquery_tool())
    reg.register(dynamics_tool())
    # The long tail of token-authed REST connectors (one spec each, built on
    # make_rest_tool). Same house rules: explicit env auth, confirm-gated writes.
    from .enterprise_connectors import enterprise_connectors
    for _conn in enterprise_connectors():
        reg.register(_conn)
    from .database_tool import database_tool
    reg.register(database_tool())
    # Credentialed SaaS/cloud tools are opt-in (PR #124): they can use
    # ambient host credentials, so they only register when the operator
    # sets MAVERICK_ENABLE_CRED_TOOLS=true.
    if _env_true("MAVERICK_ENABLE_CRED_TOOLS"):
        reg.register(airtable_tool())
        reg.register(asana_tool())
        reg.register(clickup_tool())
        reg.register(lambda_tool())
        reg.register(dynamodb_tool())
        reg.register(vercel_tool())
        reg.register(gdrive_tool())
    reg.register(trello_tool())
    reg.register(confluence_tool())
    reg.register(replicate_tool())
    reg.register(newsapi_tool())
    reg.register(wolfram_tool())
    reg.register(dropbox_tool())
    reg.register(msgraph_tool())
    reg.register(gmail_tool())
    reg.register(plausible_tool())
    reg.register(mixpanel_tool())
    reg.register(calendly_tool())
    reg.register(zoom_tool())
    reg.register(spotify_tool())
    reg.register(home_assistant_tool())
    reg.register(reddit_tool())
    reg.register(bitbucket_tool())
    reg.register(ses_tool())
    reg.register(sns_tool())
    reg.register(ffmpeg_tool(sandbox))
    reg.register(pandoc_tool(sandbox))
    reg.register(office_convert(sandbox))
    reg.register(imagemagick_tool(sandbox))
    reg.register(ga4_tool())
    reg.register(plaid_tool())
    reg.register(erp_tool())  # read-only ERP system-of-record access (Ops/Finance)

    # Voice tools (opt-in extra; tool factories raise ImportError only
    # when called without the required API key OR SDK; registering is
    # cheap).
    from .voice import speak, transcribe_audio
    reg.register(transcribe_audio(sandbox))
    reg.register(speak(sandbox))

    # Capability tools that live in the parent package (maverick/), not the
    # tools subpackage. ROADMAP 2027 H2 / 2028 H1.
    from ..browser_auth_vault import browser_auth_vault
    from ..browser_device import browser_device
    from ..continuous_benchmark import bench_track
    from ..dom_diff import dom_diff
    from ..html_to_app import html_to_app
    from ..license_scan import license_scan
    from ..task_graph import task_graph
    from ..workspace_snapshot import workspace_snapshot
    reg.register(dom_diff())
    reg.register(license_scan())
    reg.register(workspace_snapshot(sandbox))
    reg.register(task_graph())
    reg.register(browser_device())
    reg.register(bench_track())
    reg.register(html_to_app(sandbox))
    reg.register(browser_auth_vault())

    # Subpackage capability tools (ROADMAP 2027 H2). The sandbox-backed ones
    # take the sandbox; the rest are stateless.
    from .diagram_tool import diagram_tool
    from .latex_tool import latex_tool
    from .notebook_exec import notebook_exec
    from .teams_tool import teams_tool
    from .websocket_tool import websocket_tool
    reg.register(notebook_exec(sandbox))
    reg.register(latex_tool(sandbox))
    reg.register(diagram_tool(sandbox))
    reg.register(websocket_tool())
    reg.register(teams_tool())
    # self_edit intentionally is not registered in the default tool set.
    # It can edit Maverick source/config and cannot rely on a model-supplied
    # boolean as a real human approval gate. Keep it importable for explicit
    # offline diff proposal workflows, but do not expose it to agents by default.

    # Runtime / introspection tools (ROADMAP 2028 H1/H2).
    from ..cost_curve_fitter import cost_curve_tool
    from .capability_query import capability_query
    from .oidc_tool import oidc_tool
    reg.register(capability_query(user_id=user_id))
    reg.register(oidc_tool())
    reg.register(cost_curve_tool(world))

    # Zero-config BYO tools registered via the @tool decorator (any that were
    # imported before the registry was built). Never shadow a built-in.
    try:
        from .decorator import registered_tools as _byo_tools
        for _t in _byo_tools():
            if _t.name not in reg._tools:
                reg.register(_t)
    except Exception as e:  # pragma: no cover -- never block the registry
        import logging as _logging
        _logging.getLogger(__name__).warning("byo @tool load: %s", e)

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
                # Never let a plugin shadow a built-in (or an MCP) tool: an
                # allowlisted plugin returning Tool(name="shell") would silently
                # replace the real shell and run attacker code under that name.
                if t.name in reg._tools:
                    import logging
                    logging.getLogger(__name__).warning(
                        "plugin tool %r conflicts with an existing tool; skipping",
                        t.name,
                    )
                    continue
                reg.register(t)
            except Exception as e:  # pragma: no cover -- plugin failure
                import logging
                logging.getLogger(__name__).warning(
                    "plugin tool %s factory raised: %s", name, e
                )
    except Exception:  # pragma: no cover -- importlib quirks
        pass

    # Self-learning: tools the agent generated for itself on a prior run
    # live in ~/.maverick/generated_tools/ and load like first-class tools.
    # Only consulted when [self_learning] enable is set — generated tools
    # execute in-process, so the kernel never imports them by default.
    try:
        from .. import self_learning
        if self_learning.enabled():
            for t in self_learning.load_generated_tools():
                reg.register(t)
    except Exception as e:  # pragma: no cover -- never block the registry
        import logging as _logging
        _logging.getLogger(__name__).warning("generated tools load: %s", e)

    # Second rate-limit pass to cover plugin-registered tools. Earlier
    # pass already wrapped core + MCP tools; double-wrapping is avoided
    # because apply_to_registry walks the current dict snapshot.
    try:
        from ..safety.rate_limiter import apply_to_registry as _rl_apply
        _rl_apply(reg)
    except Exception:  # pragma: no cover
        pass

    # Deferred tool loading (opt-in): expose only CORE + find_tools to the
    # model; everything else (incl. MCP and plugin tools) is discovered on
    # demand. Enabled last, after every tool is registered, so the long tail
    # find_tools searches is complete.
    if _deferred_loading_enabled():
        from .find_tools import find_tools as _find_tools
        reg.register(_find_tools(reg))
        reg.enable_deferred(CORE_TOOL_NAMES)

    return reg


default_registry = base_registry
