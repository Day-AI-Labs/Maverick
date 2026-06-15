"""Recursive async agent.

v0.1.4: appends ``persona.render_persona_prompt()`` to the system
prompt of every agent so users can give the swarm a name and voice
without patching the kernel.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets as _secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import killswitch
from ._envparse import env_float, env_int
from .budget import BudgetExceeded
from .llm import model_for_role
from .swarm import SwarmContext
from .tools import ToolRegistry, base_registry
from .tools.agent_bus_tool import delegate_to_agent, recv_from_agent, send_to_agent
from .tools.spawn import (
    list_specialists_tool,
    spawn_specialist_tool,
    spawn_subagent_tool,
    spawn_swarm_tool,
)

log = logging.getLogger(__name__)

WORKER_SYSTEM_TEMPLATE = """You are a specialist agent in Maverick, a long-horizon multi-agent swarm.

Your role: {role}
Your depth in the swarm: {depth} (root = 0, max = {max_depth})

You have a single sub-goal. Plan briefly, then act.

Tools you can call include:
  - File / shell / read / write for the sandbox.
  - `ask_user` to queue a question for the user (async). Use sparingly, batch.
  - `spawn_subagent` to delegate a focused sub-task to a child specialist.
  - `spawn_swarm` to fan out INDEPENDENT sub-tasks in PARALLEL.
  - `memory` for durable, cross-session notes: consult it for long-horizon work and record lasting learnings (conventions, decisions, dead ends) — not scratch.
  - `mcp_<server>__<tool>` for any external MCP servers wired into config.

Rules:
1. Do the work YOURSELF by default. Only `spawn_swarm` when a sub-task is genuinely heavy AND independent AND needs its own context window — not merely because your task "has several aspects". Over-decomposing front-loads the whole budget on fan-out so nobody is left to synthesize the answer. The deeper you are, the more you should be a leaf: at depth ≥ 1, prefer doing the research yourself over spawning more children.
2. If a sub-task needs its own context window or a different specialty, use `spawn_subagent`.
3. When done, respond in plain text starting with `FINAL:` followed by your answer. No tool call.
4. Be precise. Cite exact paths, commands, results, and findings from your children.
5. Budget is enforced globally; spend wisely. Stop spawning if results so far are sufficient — reaching a synthesized answer matters more than breadth of research."""


ORCHESTRATOR_SYSTEM_TEMPLATE = """You are the orchestrator of a Maverick swarm.

You own a top-level goal. You do not execute work yourself; you decompose, delegate, and verify.

Standard playbook:
1. Plan: think through the goal. Identify which sub-tasks are independent (parallelizable) vs. sequential.
2. Spawn: use `spawn_swarm` to fan out independent sub-tasks in parallel. Use `spawn_subagent` for sequential dependencies.
3. Synthesize: aggregate findings from your children into a coherent answer.
4. Verify: before finalizing, check that the answer satisfies the original goal.
5. If you are blocked on info only the user can give, use `ask_user` (batched).
6. End with `FINAL:` followed by your synthesized answer.

Consult your `memory` (durable cross-session notes) when planning a long-horizon goal, and record lasting learnings there as the run progresses.

You have a maximum spawn depth of {max_depth}. Use it wisely.

Available roles for children: researcher, coder, writer, analyst, summarizer, revisor.

External MCP tools (if any) appear as `mcp_<server>__<tool>`."""


# #611: fraction of the budget reserved for the TOP-level goal's synthesis /
# write step. A deeper worker (depth > 0) stops once cumulative spend crosses
# (1 - this) of the cap, so a recursive research swarm can't burn the budget
# the orchestrator needs to actually produce the answer (the dogfooded failure:
# 35 agents, $7.85 spent, zero report). 0 disables it.
_SYNTHESIS_RESERVE = env_float("MAVERICK_SYNTHESIS_RESERVE", 0.25)

# #614: how often (seconds) the root agent mirrors running spend onto its
# open episode row so `maverick runs` / `maverick budget` show mid-run spend.
# Throttled so we don't write the row on every step of a fast loop.
_SPEND_MIRROR_INTERVAL = env_float("MAVERICK_SPEND_MIRROR_INTERVAL", 5.0)

# Loop guard: a long-horizon failure mode is the model re-issuing the SAME
# tool call that keeps failing the same way, silently burning budget/steps. We
# track a per-(tool,args) consecutive-failure streak and, once it hits the
# threshold, append a one-line nudge to the tool result so the model breaks the
# loop (change args, switch tools, rethink). Pure advice -- it never blocks a
# call. Default on; MAVERICK_LOOP_GUARD=0 disables it.
_LOOP_GUARD_ENABLED = os.environ.get("MAVERICK_LOOP_GUARD", "1").strip().lower() not in {"0", "false", "no", "off"}
_LOOP_GUARD_THRESHOLD = max(2, env_int("MAVERICK_LOOP_GUARD_THRESHOLD", 3))

# Step-budget awareness: when only this many tool-using turns remain before
# max_steps force-stops the run, the loop nudges the agent to synthesize a
# FINAL now -- otherwise a long run can get cut off mid-work with no answer.
# 0 disables the nudge. Tune via MAVERICK_STEP_BUDGET_WARNING.
_STEP_BUDGET_WARNING = max(0, env_int("MAVERICK_STEP_BUDGET_WARNING", 3))

# P0 capability layer (path resource-scopes): filesystem tools whose workspace
# paths are gated at the _run_tool chokepoint by a capability's allow_paths
# globs. Single-path tools map to the arg carrying the path. Multi-file tools
# are handled explicitly below. Empty allow_paths == all (the capability's
# "empty == allow-all" convention), so this is a no-op unless capability
# enforcement is opted in AND the active grant restricts paths.
_FILE_TOOL_PATH_ARGS: dict[str, str] = {
    "read_file": "path",
    "write_file": "path",
    "list_dir": "path",
    "str_replace_editor": "path",
    "ast_edit": "path",
    "image_content_classifier": "file",
    "wasm_run": "module",
}

# P0 capability layer (host resource-scopes): the network tools whose URL
# argument a capability's allow_hosts globs gate at the _run_tool chokepoint,
# mapped to the arg name that carries that URL. Conservative on purpose --
# only tools whose URL arg is verified against its real input_schema appear
# here. `web_search` is intentionally absent: it takes a query/site, not a URL
# to reach. The host is parsed from the URL; a URL without a host (or a missing
# arg) skips the check. Empty allow_hosts == all (the capability's "empty ==
# allow-all" convention), so this is a no-op unless capability enforcement was
# opted in AND the active grant restricts hosts.
_NET_TOOL_URL_ARGS: dict[str, str] = {
    "http_fetch": "url",
    "browser": "url",
    "oidc": "token_url",
    "oauth_helper": "token_url",
}


def _workspace_relative_path(sandbox: Any, raw_path: str) -> str:
    """Return the canonical workspace-relative path a file tool will touch.

    Filesystem tools resolve paths against ``sandbox.workdir`` before touching
    them, collapsing ``..`` components and following symlinks. Capability path
    scopes must be checked against the same canonical workspace-relative path,
    not the raw model-supplied string.
    """
    workdir = Path(sandbox.workdir).resolve()
    target = (workdir / raw_path).resolve()
    rel = target.relative_to(workdir).as_posix()
    return rel or "."


def _capability_paths_for_tool(name: str, args: Any, sandbox: Any) -> list[str] | None:
    """Canonicalize the workspace paths a tool call will touch.

    ``None`` preserves the legacy fail-soft behavior for malformed calls whose
    path cannot be located confidently; those continue to the tool's own
    validation. ``list_dir`` is special because its schema defaults a missing
    path to ``.``, and ``apply_patch`` is special because its patch can touch
    multiple files.
    """
    if not isinstance(args, dict):
        return None

    if name == "apply_patch":
        patch_text = args.get("patch")
        if not isinstance(patch_text, str):
            return None
        from .tools.apply_patch import _files_in_patch
        paths = _files_in_patch(patch_text)
        return [_workspace_relative_path(sandbox, raw) for raw in paths]

    path_arg = _FILE_TOOL_PATH_ARGS.get(name)
    if path_arg is None:
        return None

    if name == "wasm_run":
        if args.get("op", "run") != "run":
            return None
        raw_module = args.get("module")
        if not isinstance(raw_module, str) or raw_module == "":
            return None
        paths = [_workspace_relative_path(sandbox, raw_module)]
        raw_dirs = args.get("dirs") or []
        if isinstance(raw_dirs, list):
            paths.extend(
                _workspace_relative_path(sandbox, raw_dir)
                for raw_dir in raw_dirs
                if isinstance(raw_dir, str) and raw_dir != ""
            )
        return paths

    raw = args.get(path_arg, ".") if name == "list_dir" else args.get(path_arg)
    if not isinstance(raw, str):
        return None
    if raw == "" and name != "list_dir":
        return None
    return [_workspace_relative_path(sandbox, raw)]


def _governance_amount(args: Any) -> float | None:
    """Extract a transaction ``amount`` from tool args for the governance gate.

    The org policy's dollar-tier thresholds (``deny_above`` /
    ``require_human_above`` -- the finance delegation-of-authority gate) compare
    a transaction value, so the chokepoint passes the tool's conventional
    ``amount`` arg through to :func:`maverick.governance.evaluate`. Accepts a
    number or a numeric string; anything else (missing, non-numeric, bool)
    yields ``None`` so the gate stays inert -- exactly as before for tools that
    carry no amount.
    """
    if not isinstance(args, dict):
        return None
    v = args.get("amount")
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _tool_call_failed(output: str) -> bool:
    """Did a tool result represent a failure? Used for the is_error flag and the
    per-step success score.

    Looks PAST the ``<tool_output …>`` security frame to the raw content: the
    frame begins with ``<tool_output``, so a naive leading-``ERROR`` check on the
    framed string was always False -- silently never setting ``is_error`` and
    scoring every failed tool as a success. Tool-execution errors are prefixed
    ``ERROR``; shield / hook blocks (which return UNframed) start with ``⚠``.
    """
    text = output or ""
    if text.startswith("<tool_output "):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]  # drop the frame-open line; inspect the content
    return text.lstrip().startswith(("ERROR", "⚠", "BLOCKED by Shield"))


# A single runaway tool result (multi-MB shell stdout, a giant query/file dump)
# would otherwise enter the CURRENT context window uncapped -- compaction only
# trims results behind the recent window -- blowing tokens/budget in one turn.
# Cap any single result; the model keeps the head + tail and is told how to get
# the rest. ~100 KB chars (~25k tokens). Tune via MAVERICK_MAX_TOOL_RESULT_BYTES.
_MAX_TOOL_RESULT_BYTES = max(2_000, env_int("MAVERICK_MAX_TOOL_RESULT_BYTES", 100_000))


def unframe_tool_output(framed: str) -> str:
    """Recover the raw tool output from the ``<tool_output …>`` frame _run_tool
    adds. Block/error messages (shield, hooks) are returned UNframed by
    _run_tool, so they pass through unchanged. Used by code_exec to feed real
    data -- not the model-facing frame -- into a sandboxed script."""
    text = framed or ""
    if not text.startswith("<tool_output "):
        return text
    nl = text.find("\n")
    if nl == -1:
        return text
    inner = text[nl + 1:]
    close = inner.rfind("\n</tool_output ")
    if close != -1:
        inner = inner[:close]  # drop the close tag (and any loop-guard note after it)
    return inner


def _cap_tool_output(text: str) -> str:
    """Bound a single tool result so one runaway can't blow the context window.

    Keeps the head (2/3) and tail (1/3) -- results often put the actionable bit
    (an error, a summary, the last rows) at the end -- with a middle marker that
    states what was dropped and how to avoid it. A no-op below the cap, so normal
    results are byte-identical. The head is preserved, so a leading ``ERROR`` is
    intact for failure classification."""
    if not isinstance(text, str):  # defensive: never crash on a non-str result
        text = "" if text is None else str(text)
    if len(text) <= _MAX_TOOL_RESULT_BYTES:
        return text
    head = _MAX_TOOL_RESULT_BYTES * 2 // 3
    tail = _MAX_TOOL_RESULT_BYTES - head
    omitted = len(text) - head - tail
    return (
        text[:head]
        + f"\n\n... [tool output truncated: {omitted} of {len(text)} chars "
        "omitted to protect the context window. Narrow the command/query, or "
        "write the full output to a file and read it back in slices.] ...\n\n"
        + text[-tail:]
    )


def _last_assistant_text(messages: list[dict]) -> str:
    """Best-effort plain text of the most recent assistant message.

    Content may be a string or a list of content blocks; pull any text out so a
    worker that yields early (synthesis reserve) still returns its partial work.
    """
    for m in reversed(messages):
        if m.get("role") != "assistant":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c.strip()
        if isinstance(c, list):
            text = " ".join(
                b.get("text", "") for b in c
                if isinstance(b, dict) and b.get("type") == "text"
            ).strip()
            if text:
                return text
    return ""


@dataclass
class AgentResult:
    final: str | None = None
    blocked_on_user: bool = False
    error: str | None = None
    role: str = ""
    name: str = ""
    # Verifier signals (only populated on the orchestrator's FINAL).
    verifier_confidence: float = 1.0
    verifier_critique: str = ""
    # Wave 12: rendered unified diff produced by the FINAL handler
    # (SEARCH/REPLACE blocks applied + `git diff` rendered, or unified
    # diff extracted from FINAL). Best-of-N reads this directly instead
    # of re-extracting from prose at orchestrator.py:364 — the prior
    # path silently dropped SR-only candidates that produced a perfect
    # rendered diff but had no `--- a/` substring in `result`.
    final_patch: str | None = None


def _final_uncertainty_reasons(
    *,
    verifier_rejected: bool,
    verifier_incomplete: bool,
    disagreement: float,
    coding: bool,
) -> list[str]:
    """Reasons the orchestrator cannot cleanly stand behind a FINAL.

    Empty list means nothing to flag: a clean verification, or a
    sub-agent / coding-mode answer we must not wrap in prose (it may be a
    patch). The swarm-disagreement signal is added only as colour when we
    are *already* flagging uncertainty, so a reconciled-and-verified
    answer is never noised up.
    """
    if coding:
        return []
    reasons: list[str] = []
    if verifier_rejected:
        reasons.append("an internal self-check did not pass after one revision")
    if verifier_incomplete:
        reasons.append("verification did not finish within the budget")
    if reasons and disagreement >= 0.8:
        reasons.append(f"parallel attempts disagreed (entropy {disagreement:.2f})")
    return reasons


def _final_with_uncertainty_note(final: str | None, reasons: list[str]) -> str | None:
    """Prepend a brief honesty caveat to a user-facing answer.

    Leaves the answer body untouched; only adds a leading note so an
    unverified result is not handed over as if it were confirmed. No-op
    when there is nothing to flag or there is no answer text.
    """
    if not final or not reasons:
        return final
    note = (
        "⚠️ I could not fully verify this answer: "
        + "; ".join(reasons)
        + ". Treat it with caution."
    )
    return note + "\n\n" + final


_HIGH_RISK_FINAL_MARKERS = (
    "```",          # fenced code block
    "diff --git",   # unified diff
    "<<<<<<<",      # SEARCH/REPLACE edit block
    "--- a/",       # diff hunk header
)


def _risk_proportional_verify_enabled() -> bool:
    """Opt-in, off by default. Flipped on via
    ``MAVERICK_RISK_PROPORTIONAL_VERIFY=1`` or ``[verification]
    risk_proportional = true`` in config. When on, the orchestrator may
    skip the LLM verifier on clearly low-risk answers -- SWE-AF's
    ``needs_deeper_qa`` idea: spend verification where it matters.
    """
    if os.environ.get("MAVERICK_RISK_PROPORTIONAL_VERIFY", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return True
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("verification") or {}
        return bool(cfg.get("risk_proportional"))
    except Exception:
        return False


def _final_is_low_risk(final: str | None, *, coding: bool, tool_calls: int) -> bool:
    """Cheap, conservative test: safe to skip LLM verification on this answer?

    Low-risk means a short, prose-only answer the agent reached without
    touching any tools -- a pure-knowledge reply. A coding task, any tool
    use, an embedded code block / diff / edit, or a long multi-part answer
    all fall through to full verification. Intentionally narrow: it gates
    a quality check, so it only fires when skipping is clearly safe.
    """
    if coding or not final:
        return False
    if tool_calls > 0:
        return False
    text = final.strip()
    if len(text) > 800:
        return False
    return not any(marker in text for marker in _HIGH_RISK_FINAL_MARKERS)


class Agent:
    def __init__(
        self,
        ctx: SwarmContext,
        role: str,
        brief: str,
        model_override: str | None = None,
        depth: int = 0,
        parent: Agent | None = None,
        max_steps: int = 25,
        capability=None,
        domain: str | None = None,
        persona: str | None = None,
        knowledge_sources: list[str] | None = None,
    ):
        self.ctx = ctx
        self.role = role
        self.brief = brief
        self.depth = depth
        self.parent = parent
        # Long-horizon review checkpoint (root only; opt-in). Built once per
        # agent from config; None when unconfigured (the common case) so the
        # turn gate stays a no-op. The reviewer uses the consent/approval path
        # with silent auto-approval disabled, so crossing an interval requires
        # an explicit operator decision to continue.
        self._review_checkpoint = None
        if role == "orchestrator":
            try:
                from .review_checkpoint import consent_review, from_config
                _cp = from_config(
                    review=lambda event: consent_review(event, goal_id=self.ctx.goal_id)
                )
                if _cp.policy.is_active():
                    self._review_checkpoint = _cp
            except Exception:  # pragma: no cover -- never block agent construction
                self._review_checkpoint = None
        # Agent compartments: the domain/sector this agent belongs to. The
        # factory's spawn-from-profile sets it; otherwise a child inherits its
        # parent's domain so a Rung-2 sector seal catches the whole sub-tree.
        # None == unsectored (the orchestrator and ad-hoc agents).
        self.domain = domain if domain is not None else getattr(parent, "domain", None)
        # Optional domain-pack persona, appended to the system prompt below.
        self._domain_persona = persona
        # Domain knowledge collections this agent may query (the DomainProfile's
        # knowledge_sources). Children inherit the parent's, like ``domain``.
        self.knowledge_sources = (
            knowledge_sources if knowledge_sources is not None
            else list(getattr(parent, "knowledge_sources", []) or [])
        )
        # P0 identity layer: the capability grant this agent runs under. An
        # explicit arg (passed by an attenuating spawn) wins; otherwise inherit
        # the run's root grant; otherwise the depth-0 orchestrator mints the
        # root grant from config when enforcement is enabled. None ==
        # unrestricted, so enforcement is a no-op unless opted in.
        self.capability = self._resolve_capability(capability)
        # Verified peer handoffs install an attenuated task grant here; _run_tool
        # intersects it with ambient authority so verified delegations are bound
        # to execution instead of existing only as model-facing text.
        self._handoff_capability = None
        # Wave 11: Scale Labs' Pro empirical study (arxiv 2509.16941)
        # shows "most successful solutions resolve in ~25 rounds; long-
        # tail iteration past that has diminishing returns." Allow ops
        # to override globally via MAVERICK_MAX_STEPS, default 25.
        self.max_steps = env_int("MAVERICK_MAX_STEPS", max_steps)
        self.name = f"{role}-{depth}-{uuid.uuid4().hex[:6]}"

        self.tools = self._build_tools()
        self.system = self._build_system()
        self.model = model_override or model_for_role(role)
        # Per-role reasoning effort (opt-in; None unless configured). Resolved
        # once against this agent's role + model so the cost/latency lever rides
        # every LLM call this agent makes. Model-gated -> never 400s.
        from .effort import effort_for_role
        self.effort = effort_for_role(role, self.model)
        # Tracks whether we've already given one LLM-verifier-driven
        # revision pass for this agent run. Separate from
        # `_already_verified` so revised FINALs can be re-verified once
        # without permitting repeated reject/revise loops.
        self._verifier_revision_used = False

        # Process-reward model: scores each step's promise/progress. Resolved
        # from env (MAVERICK_PRM=null|heuristic|remote); default NullPRM is a
        # no-op, so this is off unless an operator opts in. Scores are emitted
        # to the blackboard (kind="prm") as an observability signal — the loop
        # does not gate on them, so a misconfigured PRM can't stall a run.
        from .prm import build_from_env
        self._prm = build_from_env()
        self._prm_enabled = type(self._prm).__name__ != "NullPRM"
        self._last_step_score = 0.5
        from .prm_guidance import PromiseWindow
        self._promise_window = PromiseWindow()
        self._last_prm_nudge_step = -100
        # Live-spend mirror throttle (#614): the root agent periodically
        # mirrors running totals onto its open episode row so `maverick runs`
        # / `maverick budget` reflect accruing mid-run spend instead of
        # $0.00 / 0 tools. Throttled to once per _SPEND_MIRROR_INTERVAL s.
        self._last_spend_mirror = 0.0
        # Loop guard: current consecutive failure streak. Grows only while the
        # exact same tool call fails with the same raw error; any intervening
        # different call or success starts a new streak.
        self._tool_fail_streak: dict[str, int] = {}

    def _resolve_capability(self, explicit):
        """Pick this agent's capability grant. Fail-open: any error or the
        disabled default yields ``None`` (unrestricted), so a misconfigured
        policy can never wedge a run."""
        if explicit is not None:
            return explicit
        inherited = getattr(self.ctx, "capability", None)
        if inherited is not None:
            return inherited
        if self.depth != 0:
            return None
        try:
            from .capability import capability_enforced, capability_from_config
            if not capability_enforced():
                return None
            root = capability_from_config(
                principal=f"user:{getattr(self.ctx, 'user_id', None) or 'local'}",
                channel=getattr(self.ctx, "channel", None),
                user_id=getattr(self.ctx, "user_id", None),
            )
            # Stash on the shared context so spawned children inherit + attenuate.
            try:
                self.ctx.capability = root
            except Exception:
                pass
            return root
        except Exception:
            return None

    @property
    def checkpoint_id(self) -> str:
        """Stable identity for durable checkpointing, distinct from ``name``.

        ``name`` carries a per-process random suffix (for blackboard / agent-bus
        uniqueness), so it can't key a checkpoint that must survive a
        fresh-process resume. The depth-0 agent is the single orchestrator of
        its episode, so ``"{role}-0"`` is stable and unique within
        (goal_id, episode_id). Phase 2 will extend this for spawned children.
        """
        return f"{self.role}-{self.depth}"

    def _build_tools(self) -> ToolRegistry:
        # Honor [capabilities] from config: these gate the optional
        # high-impact tools (computer_use / browser / web_search / mobile).
        # Without this, enabling them in config (or the wizard) was a no-op --
        # base_registry's enable_* flags defaulted off and nothing set them.
        # The [security] ACL still applies on top (a capability can be enabled
        # but a tool still denied).
        try:
            from .config import get_capabilities
            caps = get_capabilities()
        except Exception:  # pragma: no cover -- never block tool build on config
            caps = {}
        reg = base_registry(
            self.ctx.world,
            self.ctx.sandbox,
            mcp_clients=self.ctx.mcp_clients,
            goal_id=self.ctx.goal_id,
            channel=self.ctx.channel,
            user_id=self.ctx.user_id,
            budget=self.ctx.budget,
            enable_computer_use=bool(caps.get("computer_use", False)),
            enable_browser=bool(caps.get("browser", False)),
            enable_web_search=bool(caps.get("web_search", False)),
            enable_mobile_tools=bool(caps.get("mobile_tools", False)),
            enable_ros=bool(caps.get("ros", False)),
        )
        # Cross-agent bus tools, bound to this agent's id so send records
        # the right sender and recv drains the right inbox.
        reg.register(send_to_agent(self.name))
        # recv is handoff-aware (verifies a signed delegation via the run's
        # handoff authority); delegate_to_agent is the producer, offered only
        # when capability enforcement is on -- otherwise a handoff is just a
        # plain message and send_to_agent already covers it.
        reg.register(recv_from_agent(self.name, agent=self))
        from .capability import capability_enforced
        if capability_enforced():
            reg.register(delegate_to_agent(self))
        if self.depth < self.ctx.max_depth:
            reg.register(spawn_subagent_tool(self))
            reg.register(spawn_swarm_tool(self))
            # The bridge from the suite roster to the running fleet: deploy a
            # curated domain pack as a specialist child (persona + compartment +
            # attenuated envelope), and discover what's available.
            reg.register(spawn_specialist_tool(self))
            reg.register(list_specialists_tool())
        # Per-domain document knowledge: bind a knowledge_search tool to this
        # agent's collections when a knowledge base is configured for the run.
        kb = getattr(self.ctx, "knowledge", None)
        sources = self.knowledge_sources or ([self.domain] if self.domain else [])
        if kb is not None and sources:
            from .tools.knowledge import knowledge_search_tool
            reg.register(knowledge_search_tool(kb, sources))
        # Self-learning: bound to this agent so it can hot-register a newly
        # acquired tool / MCP server into THIS run's live registry. Off
        # unless [self_learning] enable is set (kernel rule 1).
        try:
            from . import self_learning
            if self_learning.enabled():
                from .tools.learn import learn_capability
                reg.register(learn_capability(self))
        except Exception as e:  # pragma: no cover -- never block tool build
            log.debug("self_learning tool registration skipped: %s", e)
        # Programmatic tool calling (opt-in): a sandboxed Python script that
        # orchestrates declared tool calls, keeping their raw outputs out of the
        # model's context. Powerful (runs code + tools), so off unless enabled
        # via [capabilities] code_exec or MAVERICK_CODE_EXEC.
        code_exec_on = caps.get("code_exec", False) or (
            os.environ.get("MAVERICK_CODE_EXEC", "").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        if code_exec_on:
            from .tools.code_exec import code_exec_tool
            reg.register(code_exec_tool(self))
        # Deferred tool loading (default ON): hide the SaaS-connector long
        # tail behind the find_tools meta-tool so the model's catalog stays
        # lean -- 470+ connector schemas rode EVERY model turn at consumer
        # defaults (observed: 601 tools offered per call), dominating context
        # cost. The mechanism (ToolRegistry.enable_deferred / find_tools)
        # already existed and was tested; nothing wired it. Everything
        # registered above (file/shell/spawn/bus/memory/MCP/...) stays
        # visible; only base_registry's marked long tail defers, and run()
        # still executes ANY registered tool, so execution semantics are
        # unchanged. Disable via [capabilities] deferred_tools = false or
        # MAVERICK_DEFERRED_TOOLS=0.
        env_dt = os.environ.get("MAVERICK_DEFERRED_TOOLS", "").strip().lower()
        if env_dt in {"0", "false", "no", "off"}:
            deferred_on = False
        elif env_dt in {"1", "true", "yes", "on"}:
            deferred_on = True
        else:
            deferred_on = bool(caps.get("deferred_tools", True))
        deferrable = getattr(reg, "deferrable_names", None) or set()
        if deferred_on and deferrable:
            from .tools.find_tools import find_tools
            reg.register(find_tools(reg))
            reg.enable_deferred(core={t.name for t in reg.all()} - set(deferrable))
        return reg

    def _build_system(self) -> str:
        # Wave 9 fix: coding mode applies to the ORCHESTRATOR too, not
        # just workers. The orchestrator emits the FINAL; if it's still
        # using ORCHESTRATOR_SYSTEM_TEMPLATE (prose-oriented), the patch
        # validator + test-driven verifier both operate on prose, every
        # extract_unified_diff returns None, every git apply --check
        # rejects -> Wave 8 contributes negative value. (council code
        # reviewer finding #1)
        try:
            from .coding_mode import CODER_CODING_MODE_TEMPLATE
            from .coding_mode import from_env as _cm_from_env
            _coding_cfg = _cm_from_env()
        except Exception:
            _coding_cfg = None

        if _coding_cfg is not None and _coding_cfg.enabled:
            base = CODER_CODING_MODE_TEMPLATE.format(
                role=self.role, depth=self.depth, max_depth=self.ctx.max_depth,
            )
        elif self.role == "orchestrator":
            base = ORCHESTRATOR_SYSTEM_TEMPLATE.format(max_depth=self.ctx.max_depth)
        else:
            base = WORKER_SYSTEM_TEMPLATE.format(
                role=self.role, depth=self.depth, max_depth=self.ctx.max_depth
            )

        # Persona (optional, additive).
        try:
            from .persona import render_persona_prompt
            persona = render_persona_prompt()
            if persona:
                base = base + persona
        except Exception:
            pass

        # Per-role client addendum (optional, additive): a tenant's custom
        # instructions for this role, edited via the dashboard roles editor.
        # Empty for any role the client hasn't customized, so behavior is
        # unchanged by default. Specialist roles (domain-pack names) never
        # match a known role, so this is a no-op for them.
        try:
            from .role_edit import role_addendum
            addendum = role_addendum(self.role)
            if addendum:
                base = base + "\n\n" + addendum
        except Exception:
            pass

        # Domain-pack persona (factory spawn-from-profile): specialist
        # instructions for this agent's domain, additive to the base template.
        if self._domain_persona:
            base = base + "\n\n" + self._domain_persona

        # Skills from prior runs (existing logic).
        if self.ctx.use_skills:
            try:
                from .skills import available_skills, relevant_skills, render_for_prompt
                skills = relevant_skills(self.brief, available_skills())
                if skills:
                    base = base + "\n\n" + render_for_prompt(skills)
                    # Record the recall and remember the names so the
                    # orchestrator can attribute this run's outcome to them
                    # at finalize. Fully fail-safe: stats are an optimization.
                    try:
                        from . import skill_stats
                        names = [s.name for s in skills]
                        skill_stats.record_use(names)
                        self.ctx.skills_used.update(names)
                    except Exception:
                        pass
            except (ImportError, FileNotFoundError, ValueError):
                pass

        # Cross-session memory (root agent only): surface only a safe presence
        # hint so each run knows durable memory exists. Memory filenames and
        # contents are model-writable/untrusted and must re-enter through the
        # `memory` tool's normal scanned, redacted, framed output path. Empty
        # memory -> "" -> no change. Depth-gated so deep workers keep lean,
        # focused context (they can still use the tool directly).
        if self.depth == 0:
            try:
                from .tools.memory import memory_brief
                brief = memory_brief()
                if brief:
                    base = base + "\n\n" + brief
            except Exception:  # pragma: no cover -- never block a run
                pass

        return base

    def _thinking_budget(self) -> int | None:
        base = 8000 if self.role in ("orchestrator", "revisor") else None
        # Adaptive controller (opt-in, default off): trims/raises by recent
        # success rate. Disabled or low-data -> returns `base` unchanged.
        from .thinking_budget import adjust
        return adjust(self.role, base)

    def _extract_and_apply_patch(self, final: str):
        """Wave 11: unify SEARCH/REPLACE and unified-diff extraction.

        Returns (patch_str_or_None, sr_summary_or_None). The patch is
        the rendered unified diff (suitable for `git apply --check` /
        the CSV). The `sr_summary` is the ApplySummary when blocks
        were applied to disk, None when only a unified diff was found.

        Caller is responsible for resetting the workdir AFTER capturing
        the patch.

        Wave 11: also runs `ast.parse` on every modified Python file
        before rendering the diff. SyntaxError gets surfaced via a
        synthesized ApplySummary so the agent re-emits, instead of
        submitting a patch that breaks pytest collection (32% of Opus
        4.1 / 57% of Gemini failures on Pro per Scale's Table 4).
        """
        from pathlib import Path as _Path

        from .coding_mode import (
            _ast_check_python_files,
            extract_unified_diff,
        )
        from .edit_format import (
            ApplyResult,
            ApplySummary,
            SearchReplaceBlock,
            apply_blocks,
            parse_blocks,
            render_diff,
        )

        workdir = _Path(getattr(self.ctx.sandbox, "workdir", "."))
        blocks = parse_blocks(final)
        if blocks:
            import subprocess as _sub
            import tempfile as _tempfile

            sandbox = self.ctx.sandbox
            has_exec = sandbox is not None and hasattr(sandbox, "exec")
            apply_workdir = workdir
            temp_root = None
            used_temp_worktree = False

            if has_exec:
                # SEARCH/REPLACE application is necessarily host-local
                # because it rewrites files via pathlib.  Do it in a
                # disposable git worktree so exec-backed sandboxes (ssh,
                # k8s, firecracker/E2B) cannot leave attacker-influenced
                # edits behind in a host checkout while _reset_workdir()
                # resets a different backend filesystem.
                temp_root = _tempfile.TemporaryDirectory(
                    prefix="maverick-sr-worktree-"
                )
                candidate = _Path(temp_root.name) / "worktree"
                hooks_dir = _Path(temp_root.name) / "hooks"
                try:
                    hooks_dir.mkdir(mode=0o700)
                    wt = _sub.run(
                        [
                            "git", "-c", f"core.hooksPath={hooks_dir}",
                            "-C", str(workdir), "worktree", "add",
                            "--detach", "--quiet", str(candidate), "HEAD",
                        ],
                        capture_output=True, timeout=60,
                    )
                    if wt.returncode != 0:
                        raise RuntimeError(
                            wt.stderr.decode("utf-8", errors="replace")
                        )
                    apply_workdir = candidate
                    used_temp_worktree = True
                except Exception as exc:
                    temp_root.cleanup()
                    summary = ApplySummary()
                    summary.results.append(ApplyResult(
                        ok=False,
                        block=SearchReplaceBlock(
                            path="<sandboxed search/replace>",
                            search="", replace="",
                        ),
                        reason=(
                            "SEARCH/REPLACE requires a disposable local git "
                            f"worktree when sandbox.exec is available: {exc}"
                        ),
                    ))
                    return None, summary

            try:
                summary = apply_blocks(blocks, apply_workdir, atomic=True)
                if not summary.ok:
                    return None, summary
                touched_paths = sorted(summary.files_touched)
                syntax_errors = _ast_check_python_files(
                    apply_workdir, touched_paths
                )
                if syntax_errors:
                    # Roll back the SR application so the next attempt sees
                    # HEAD, then synthesise a failure summary the caller
                    # can convert into a repair prompt.  Disposable
                    # worktrees are cleaned below; only reset the real
                    # workdir on the legacy no-exec path.
                    if not used_temp_worktree:
                        self._reset_workdir()
                    summary.results.append(ApplyResult(
                        ok=False,
                        block=SearchReplaceBlock(
                            path="<syntax check>", search="", replace="",
                        ),
                        reason=(
                            "Python syntax errors after applying: "
                            + "; ".join(syntax_errors)
                        ),
                    ))
                    return None, summary
                patch = render_diff(apply_workdir, paths=touched_paths)
                return patch, summary
            finally:
                if used_temp_worktree:
                    try:
                        _sub.run(
                            [
                                "git", "-C", str(workdir), "worktree",
                                "remove", "--force", str(apply_workdir),
                            ],
                            capture_output=True, timeout=30,
                        )
                    except Exception:
                        pass
                if temp_root is not None:
                    temp_root.cleanup()
        return extract_unified_diff(final), None

    def _reset_workdir(self) -> None:
        """Revert the sandbox workdir to a clean HEAD.

        CLAUDE.md rule 4: route git plumbing through ``sandbox.exec`` so
        it operates on the configured backend's filesystem (ssh/k8s/fc),
        not the host. ``reset --hard`` then ``clean -fd`` in one shell
        string; we only need the exit code, so the 8000-char output
        truncation is irrelevant here. Falls back to host ``subprocess``
        only when there's no sandbox or it lacks ``exec``.
        """
        sandbox = self.ctx.sandbox
        if sandbox is not None and hasattr(sandbox, "exec"):
            try:
                sandbox.exec("git reset --hard HEAD && git clean -fd", timeout=30)
            except Exception:
                pass
            return
        import subprocess as _sub
        from pathlib import Path as _Path
        workdir = _Path(getattr(sandbox, "workdir", "."))
        try:
            _sub.run(
                ["git", "-C", str(workdir), "reset", "--hard", "HEAD"],
                capture_output=True, timeout=20,
            )
            _sub.run(
                ["git", "-C", str(workdir), "clean", "-fd"],
                capture_output=True, timeout=20,
            )
        except Exception:
            pass

    def _git_apply(self, patch: str) -> bool:
        """Apply ``patch`` to the sandbox workdir; return whether it applied.

        CLAUDE.md rule 4: run ``git apply`` on the configured backend.
        ``sandbox.exec`` runs a shell string and can't pipe stdin, so we
        write the patch to a temp file inside the workdir and
        ``git apply <tmpfile>``, then clean the temp file up. Falls back
        to host ``subprocess`` (piping via stdin) only when there's no
        sandbox or it lacks ``exec``.
        """
        from pathlib import Path as _Path
        sandbox = self.ctx.sandbox
        workdir = _Path(getattr(sandbox, "workdir", "."))
        if sandbox is not None and hasattr(sandbox, "exec"):
            import os as _os
            import tempfile as _tempfile
            tmp_path = None
            try:
                with _tempfile.NamedTemporaryFile(
                    mode="w", suffix=".patch", dir=str(workdir),
                    delete=False, encoding="utf-8",
                ) as tmp:
                    tmp.write(patch)
                    tmp_path = tmp.name
                import shlex as _shlex
                rel = _shlex.quote(_os.path.basename(tmp_path))
                res = sandbox.exec(f"git apply {rel}", timeout=30)
                return getattr(res, "exit_code", 1) == 0
            except Exception:
                return False
            finally:
                if tmp_path is not None:
                    try:
                        _os.unlink(tmp_path)
                    except OSError:
                        pass
        import subprocess as _sub
        try:
            ap = _sub.run(
                ["git", "-C", str(workdir), "apply", "-"],
                input=patch.encode("utf-8"),
                capture_output=True, timeout=30,
            )
            return ap.returncode == 0
        except Exception:
            return False

    def _maybe_seal(self, quarantine, verdict) -> None:
        """Conservatively escalate a shield block to a Rung-1 seal.

        Workers only; the trusted root orchestrator (the privileged promoter)
        is never sealed. Do not trust ``role`` alone here: child agents receive
        model-supplied role strings from spawn tools. Fail-open -- containment
        must never break the agent loop.
        """
        is_root_orchestrator = (
            getattr(self, "role", "") == "orchestrator"
            and getattr(self, "depth", None) == 0
            and getattr(self, "parent", None) is None
        )
        if quarantine is None or is_root_orchestrator:
            return
        try:
            from .quarantine import triage_block
            triage_block(
                quarantine, self.name,
                getattr(verdict, "severity", "high"),
                "; ".join(getattr(verdict, "reasons", []) or []),
            )
        except Exception:  # pragma: no cover -- containment must never break the loop
            pass

    def _effective_capability(self, tool_name: str):
        """Capability that gates a tool call, including active verified handoffs."""
        ambient = getattr(self, "capability", None)
        # Receiving bus messages is the control-plane path that lets an agent
        # accept a replacement handoff. Keep it governed by ambient authority so
        # an older task grant cannot strand the peer from future coordination.
        if tool_name == "recv_from_agent":
            return ambient
        handoff = getattr(self, "_handoff_capability", None)
        if handoff is None:
            return ambient
        if ambient is None:
            return handoff
        try:
            return ambient.intersect(handoff, principal=handoff.principal)
        except AttributeError:  # pragma: no cover -- defensive for foreign caps
            return ambient

    def _capability_revocation_denial(self, name: str, cap) -> str | None:
        # Revocation kill-switch: a still-valid grant can be revoked out of
        # band (leaked key / rogue agent / offboard); the registry is re-read
        # on change so a revoke in another process reaches this running agent.
        # Fail-open (revocation never bricks a run) and only when a grant
        # exists (== capability enforcement is on).
        if cap is None:
            return None
        from .revocation import revoked_principal as _revoked_principal
        principals = (
            cap.revocation_principals()
            if hasattr(cap, "revocation_principals") else (cap.principal,)
        )
        revoked = _revoked_principal(principals)
        if revoked is None:
            return None
        self.ctx.blackboard.post(
            self.name, "error",
            f"tool={name} DENIED: principal {revoked} REVOKED",
        )
        try:  # tamper-evident record of the denial; never block on audit
            from .audit import EventKind, record
            record(
                EventKind.CAPABILITY_DENIED,
                agent=self.name,
                goal_id=self.ctx.goal_id,
                tool=name,
                principal=cap.principal,
                revoked_principal=revoked,
                channel=getattr(self.ctx, "channel", None),
                user_id=getattr(self.ctx, "user_id", None),
            )
        except Exception:  # pragma: no cover
            pass
        return (
            f"⚠ DENIED by capability policy: principal {revoked!r} "
            f"has been revoked. The tool was not executed."
        )

    def _capability_permits_denial(self, name: str, cap) -> str | None:
        if cap is None or cap.permits(name):
            return None
        self.ctx.blackboard.post(
            self.name, "error",
            f"tool={name} DENIED by capability (principal={cap.principal})",
        )
        try:  # tamper-evident record of the denial; never block on audit
            from .audit import EventKind, record
            record(
                EventKind.CAPABILITY_DENIED,
                agent=self.name,
                goal_id=self.ctx.goal_id,
                tool=name,
                principal=cap.principal,
                channel=getattr(self.ctx, "channel", None),
                user_id=getattr(self.ctx, "user_id", None),
            )
        except Exception:  # pragma: no cover
            pass
        return (
            f"⚠ DENIED by capability policy: principal {cap.principal!r} is "
            f"not granted tool {name!r}. The tool was not executed."
        )

    def _capability_path_denial(self, name: str, args: dict, cap) -> str | None:
        # P0 capability layer (path resource-scopes): for known filesystem
        # tools, gate the canonical workspace-relative path(s) they will touch.
        # This mirrors the tools' own resolution behavior, so raw paths like
        # "allowed/../secret.txt" are checked as "secret.txt". ``list_dir``
        # gets its schema default of ".", and ``apply_patch`` checks every
        # file referenced by the unified diff. Malformed calls whose path
        # cannot be located still fall through to tool validation.
        if cap is None or not (name in _FILE_TOOL_PATH_ARGS or name == "apply_patch"):
            return None
        denied_paths: list[str] = []
        try:
            paths = _capability_paths_for_tool(name, args, self.ctx.sandbox)
        except ValueError as e:
            denied_paths = [str(e)]
        else:
            if paths is not None:
                denied_paths = [p for p in paths if not cap.permits_path(p)]
        if not denied_paths:
            return None
        denied = ", ".join(denied_paths)
        self.ctx.blackboard.post(
            self.name, "error",
            f"tool={name} path={denied} DENIED by capability "
            f"(principal={cap.principal})",
        )
        try:  # tamper-evident record of the denial; never block on audit
            from .audit import EventKind, record
            record(EventKind.CAPABILITY_DENIED, agent=self.name,
                   goal_id=self.ctx.goal_id, tool=name,
                   principal=cap.principal, path=denied)
        except Exception:  # pragma: no cover
            pass
        return (
            f"⚠ DENIED by capability policy: principal {cap.principal!r} is "
            f"not granted path {denied!r} for tool {name!r}. "
            "The tool was not executed."
        )

    def _capability_host_denial(self, name: str, args: dict, cap) -> str | None:
        # P0 capability layer (host resource-scopes): for a known network tool,
        # the grant's allow_hosts globs also gate the host its URL reaches.
        # No-op unless a host-restricted grant is active (empty == all). Fail-
        # soft: if the URL arg is missing/unparseable (no host) we skip the
        # check rather than error -- we never deny something we can't
        # confidently locate the host for.
        url_arg = _NET_TOOL_URL_ARGS.get(name)
        if cap is None or url_arg is None:
            return None
        raw = args.get(url_arg) if isinstance(args, dict) else None
        host = None
        if isinstance(raw, str) and raw:
            try:  # malformed URLs (e.g. bad IPv6) raise -- skip, don't crash
                host = urlsplit(raw).hostname
            except ValueError:
                host = None
        if not host or cap.permits_host(host):
            return None
        self.ctx.blackboard.post(
            self.name, "error",
            f"tool={name} host={host} DENIED by capability "
            f"(principal={cap.principal})",
        )
        try:  # tamper-evident record of the denial; never block on audit
            from .audit import EventKind, record
            record(EventKind.CAPABILITY_DENIED, agent=self.name,
                   goal_id=self.ctx.goal_id, tool=name,
                   principal=cap.principal, host=host)
        except Exception:  # pragma: no cover
            pass
        return (
            f"⚠ DENIED by capability policy: principal {cap.principal!r} is "
            f"not granted host {host!r} for tool {name!r}. "
            "The tool was not executed."
        )

    def _autonomy_denial(self, name: str, cap) -> str | None:
        # Autonomy servo (Loop 2): tighten the leash with live trust. When the
        # run's trust is low -- a high-disagreement swarm fan-out or a low
        # verifier verdict -- the effective risk ceiling drops, so an unresolved
        # disagreement can't drive an irreversible (high-risk) action
        # unattended. Composes WITH the capability ceiling above (it tightens
        # from the grant's max_risk, never broadens). No-op unless [autonomy] is
        # enabled. Fail-open: a bug here must never block a tool.
        try:
            from . import autonomy
            _av = autonomy.gate_tool(
                name,
                disagreement=float(getattr(self.ctx, "last_disagreement", 0.0) or 0.0),
                verifier_confidence=float(
                    getattr(self.ctx, "last_verifier_confidence", 1.0) or 1.0
                ),
                configured_max_risk=getattr(cap, "max_risk", None),
            )
        except Exception:  # pragma: no cover -- autonomy gate must never break the loop
            _av = None
        if _av is None or _av.allowed:
            return None
        self.ctx.blackboard.post(
            self.name, "error", f"tool={name} GATED by autonomy: {_av.reason}",
        )
        try:  # tamper-evident record of the gate; never block on audit
            from .audit import EventKind, record
            record(
                EventKind.AUTONOMY_GATED, agent=self.name,
                goal_id=self.ctx.goal_id, tool=name,
                effective_max_risk=_av.effective_max_risk,
            )
        except Exception:  # pragma: no cover
            pass
        return (
            f"⚠ GATED by autonomy policy: {_av.reason}. The tool was not "
            "executed. Resolve the disagreement (reconcile the divergent "
            "findings) or get human approval via ask_user before retrying."
        )

    async def _governance_denial(self, name: str, args: dict, cap) -> str | None:
        # Org oversight control plane (enterprise): on top of the per-principal
        # capability above, an org-level policy can DENY an action outright or
        # REQUIRE_HUMAN sign-off (EU AI Act Art 14). Default-open -- an empty
        # [governance] policy returns ALLOW, so this is a no-op for non-
        # enterprise installs. Fail behaviour is split (hardening): if a policy
        # IS configured but evaluating THIS action errors, fail CLOSED + log
        # loudly -- a config/classifier bug must never silently bypass the
        # oversight gate. If governance/config can't load at all (can't even
        # tell a policy is set), fail open + log, so a broken import never wedges
        # every tool for non-enterprise installs.
        _gov = None
        try:
            from .governance import Decision as _GovDecision
            from .governance import Policy as _GovPolicy
            from .governance import Verdict as _GovVerdict
            from .governance import evaluate as _gov_evaluate
            _gov_policy = _GovPolicy.from_config()
        except Exception:  # governance unavailable -> can't enforce; fail open (logged)
            log.warning("governance: unavailable; enforcement skipped for %r", name)
            _gov_policy = None
        if _gov_policy is not None and not _gov_policy.is_empty():
            try:
                # Pass the transaction amount/currency so the policy's
                # dollar-tier gates (deny_above / require_human_above) actually
                # fire -- without this the finance delegation-of-authority
                # thresholds are dead at the chokepoint.
                _gov_currency = args.get("currency") if isinstance(args, dict) else None
                _gov = _gov_evaluate(
                    name, policy=_gov_policy,
                    amount=_governance_amount(args),
                    currency=_gov_currency if isinstance(_gov_currency, str) else "",
                )
            except Exception:
                log.warning("governance: evaluation failed for %r; failing closed",
                            name, exc_info=True)
                self.ctx.blackboard.post(
                    self.name, "error",
                    f"tool={name} BLOCKED: governance evaluation error (fail-closed)",
                )
                _gov = _GovVerdict(
                    _GovDecision.DENY,
                    "governance evaluation error (failed closed)", "error",
                )
        if _gov is None or _gov.decision is _GovDecision.ALLOW:
            return None
        from .audit import EventKind, record
        _principal = getattr(cap, "principal", None) if cap is not None else None
        if _gov.decision is _GovDecision.DENY:
            self.ctx.blackboard.post(
                self.name, "error",
                f"tool={name} DENIED by governance ({_gov.rule})",
            )
            try:  # tamper-evident record of the denial; never block on audit
                record(EventKind.GOVERNANCE_DENIED, agent=self.name,
                       goal_id=self.ctx.goal_id, tool=name,
                       principal=_principal, rule=_gov.rule, reason=_gov.reason)
            except Exception:  # pragma: no cover
                pass
            return (
                f"⚠ DENIED by org policy ({_gov.rule}): {_gov.reason}. "
                "The tool was not executed."
            )
        # REQUIRE_HUMAN: the action runs only with a real human's approval
        # (Art 14). allow_auto_approve=False means a silent auto-approve mode
        # counts as a denial -- no human in the loop, no run.
        import asyncio as _asyncio
        granted = False
        try:
            from .safety.consent import require_consent
            from .safety.tool_risk import tool_risk
            decision = await _asyncio.to_thread(
                require_consent, name,
                risk=tool_risk(name), detail=_gov.reason,
                provenance="governance",
                allow_auto_approve=False,
                # When the operator opts into per-action oversight, a prior
                # persistent ledger grant must NOT silently satisfy the
                # Art-14 gate -- demand a fresh human decision each time.
                consult_ledger=not _gov_policy.require_fresh_human_approval,
            )
            granted = bool(decision.granted)
        except Exception:  # pragma: no cover -- consent unavailable -> fail closed
            granted = False
        if granted:
            return None
        self.ctx.blackboard.post(
            self.name, "error",
            f"tool={name} BLOCKED: governance requires human approval",
        )
        try:
            record(EventKind.GOVERNANCE_DENIED, agent=self.name,
                   goal_id=self.ctx.goal_id, tool=name,
                   principal=_principal, rule=_gov.rule,
                   reason="human approval not granted")
        except Exception:  # pragma: no cover
            pass
        # Human-override ingestion: the operator's "no" is itself a
        # learning signal — recallable on the next similar goal and
        # consolidated by dreaming. No-op unless [reflexion] is on.
        try:
            from .reflexion import record_human_override
            record_human_override(
                self.brief, name, _gov.reason or _gov.rule,
                domain=self.domain,
            )
        except Exception:  # pragma: no cover -- never block the denial
            pass
        return (
            f"⚠ {name!r} requires human approval (EU AI Act Art 14): "
            f"{_gov.reason}. Not granted, so the tool was not executed."
        )

    async def _run_tool(self, name: str, args: dict) -> str:
        # Record the tool name on this agent's action sequence so a parent can
        # capture per-sub-agent trajectories (maverick.credit.build_subtrajectories).
        # Tool NAMES only -- never args -- so this carries no secrets. Lazy-init
        # to avoid touching the constructor.
        acts = getattr(self, "_actions", None)
        if acts is None:
            acts = self._actions = []
        acts.append(name)
        # Compartment Rung 1: a sealed agent runs no further tools. Its prior
        # blackboard posts are also withheld (see Blackboard.render).
        q = getattr(self.ctx, "quarantine", None)
        if q is not None:
            # Register this agent's domain so a Rung-2 sector seal reaches it.
            q.register_agent(self.name, getattr(self, "domain", None))
            if q.is_sealed(self.name):
                return (
                    f"⚠ Agent sealed by compartment quarantine "
                    f"({q.reason(self.name)}). No further tools will run."
                )
        shield = self.ctx.shield
        if shield is not None:
            verdict = shield.scan_tool_call(name, args)
            if not verdict.allowed:
                self.ctx.blackboard.post(
                    self.name, "error",
                    f"tool={name} BLOCKED by Shield: {'; '.join(verdict.reasons)}",
                )
                try:  # tamper-evident record of the shield block; never block on audit
                    from .audit import EventKind, record
                    record(EventKind.SHIELD_BLOCK, agent=self.name,
                           goal_id=self.ctx.goal_id, stage="tool",
                           reason="; ".join(verdict.reasons),
                           score=getattr(verdict, "score", None))
                except Exception:  # pragma: no cover
                    pass
                self._maybe_seal(q, verdict)
                return (
                    f"⚠ BLOCKED by Shield ({verdict.severity}): "
                    f"{'; '.join(verdict.reasons)}. The tool was not executed."
                )

        # P0 capability layer: a per-agent grant (attenuated from the parent
        # on spawn) gates the tool surface. None == unrestricted, so this is a
        # no-op unless capability enforcement was opted in. Deny wins -- the
        # tool never runs and the model gets a clear, non-leaky refusal.
        cap = self._effective_capability(name)
        # Capability gates (revocation kill-switch, tool grant, path scopes).
        # Each returns a non-leaky refusal string when it denies, else None.
        if (d := self._capability_revocation_denial(name, cap)) is not None:
            return d
        if (d := self._capability_permits_denial(name, cap)) is not None:
            return d
        if (d := self._capability_path_denial(name, args, cap)) is not None:
            return d
        # The browser can follow redirects and later URL-less actions read or
        # interact with the current page. Pass the active host scope into the
        # tool so it can gate the final/current page host before returning
        # content or continuing a restricted session. This must happen before
        # the host-scope check so the (possibly rewritten) args carry forward.
        if cap is not None and name == "browser" and cap.allow_hosts and isinstance(args, dict):
            args = dict(args)
            args["_capability_allow_hosts"] = tuple(cap.allow_hosts)
        if (d := self._capability_host_denial(name, args, cap)) is not None:
            return d

        # Autonomy servo (Loop 2): low run-trust tightens the risk ceiling.
        if (d := self._autonomy_denial(name, cap)) is not None:
            return d

        # Org oversight control plane (enterprise): policy DENY or REQUIRE_HUMAN
        # sign-off (EU AI Act Art 14). Default-open for non-enterprise installs.
        if (d := await self._governance_denial(name, args, cap)) is not None:
            return d

        # PreToolUse hooks: any registered hook can BLOCK the call by
        # returning a non-zero exit code (shell hook) or a falsy value
        # (Python callable). Modeled on Claude Code's hook surface.
        from .hooks import HookContext, HookEvent
        from .hooks import dispatch as _dispatch_hooks
        pre_ctx = HookContext(
            event=HookEvent.PRE_TOOL_USE,
            tool_name=name, tool_args=args,
            goal_id=self.ctx.goal_id, agent_role=self.role,
        )
        if not await _dispatch_hooks(pre_ctx):
            self.ctx.blackboard.post(
                self.name, "error",
                f"tool={name} BLOCKED by PreToolUse hook",
            )
            return "⚠ BLOCKED by hook. The tool was not executed."

        output = await self.tools.run(name, args)

        post_ctx = HookContext(
            event=HookEvent.POST_TOOL_USE,
            tool_name=name, tool_args=args, tool_result=output,
            goal_id=self.ctx.goal_id, agent_role=self.role,
        )
        await _dispatch_hooks(post_ctx)
        # Council finding: tool output flowed back to the LLM unscanned,
        # so a malicious file contents / shell stdout containing
        # `FINAL: <exfil>` or jailbreak instructions hit the next turn.
        # Wrap the output in a clearly-delimited block so the agent
        # treats it as data, and scan it through the shield.
        if shield is not None:
            try:
                out_verdict = shield.scan_output(output)
                if not out_verdict.allowed:
                    self.ctx.blackboard.post(
                        self.name, "error",
                        f"tool={name} OUTPUT BLOCKED by Shield: "
                        f"{'; '.join(out_verdict.reasons)}",
                    )
                    self._maybe_seal(q, out_verdict)
                    return (
                        f"⚠ Tool output BLOCKED by Shield ({out_verdict.severity}): "
                        f"{'; '.join(out_verdict.reasons)}. Result withheld."
                    )
            except Exception as e:  # shield must never block tools on its own bug
                # Fail-open, but NOT silently: a scanner that reliably throws
                # on a crafted output would otherwise disable output gating for
                # that call with zero trace. Surface it so the bypass is
                # observable (warn + blackboard), per the "warn, don't fail
                # silent" contract.
                log.warning(
                    "shield.scan_output raised on tool=%s output (fail-open): %s: %s",
                    name, type(e).__name__, e,
                )
                self.ctx.blackboard.post(
                    self.name, "warning",
                    f"tool={name} shield output-scan errored (fail-open): "
                    f"{type(e).__name__}",
                )
        # Defense-in-depth: redact secrets in tool output BEFORE it returns to
        # the model / blackboard / channel. `cat .env`, a DB row, or an API
        # response can carry a key the shield's scan_output doesn't classify
        # as a policy violation; the env-scrub only covers the shell child's
        # own env, not secrets the tool reads from files/services. Fail-open.
        try:
            from .safety.secret_detector import redact as _redact_secrets
            output, _redacted = _redact_secrets(output)
        except Exception:  # pragma: no cover
            pass
        # Bound a single runaway result before it enters the context window
        # (compaction only trims results behind the recent window).
        output = _cap_tool_output(output)
        # Council-of-20 security finding: a literal `</tool_output>` in
        # `output` (attacker-controlled file contents, shell stdout, MCP
        # response) escapes the framing and lets following text read as
        # authoritative LLM context. Use a random per-call nonce so the
        # close tag is unforgeable. `secrets.token_hex(8)` = 16 hex chars.
        nonce = _secrets.token_hex(8)
        framed = (
            f"<tool_output tool={name!r} id={nonce}>\n"
            f"{output}\n"
            f"</tool_output {nonce}>"
        )
        # Loop guard: detect a repeated identical FAILURE from the raw result
        # (before framing) and, past threshold, append a nudge OUTSIDE the data
        # block -- it's trusted loop-control guidance, not tool output.
        return framed + self._loop_guard_note(name, args, output)

    @staticmethod
    def _tool_call_key(name: str, args: dict) -> str:
        try:
            blob = json.dumps(args, sort_keys=True, default=str)
        except Exception:  # pragma: no cover -- unserializable args
            blob = repr(args)
        return f"{name}\x00{blob}"

    @staticmethod
    def _tool_failure_key(name: str, args: dict, raw_output: str) -> str:
        error_hash = hashlib.sha256((raw_output or "").strip().encode()).hexdigest()
        return f"{Agent._tool_call_key(name, args)}\x00{error_hash}"

    def _loop_guard_note(self, name: str, args: dict, raw_output: str) -> str:
        """Track this call's outcome; return a nudge when an identical call has
        failed the same way ``_LOOP_GUARD_THRESHOLD`` times in a row."""
        if not _LOOP_GUARD_ENABLED:
            return ""
        failed = _tool_call_failed(raw_output)
        if not failed:
            self._tool_fail_streak.clear()
            return ""
        key = self._tool_failure_key(name, args, raw_output)
        streak = self._tool_fail_streak.get(key, 0) + 1
        self._tool_fail_streak.clear()
        self._tool_fail_streak[key] = streak
        if streak < _LOOP_GUARD_THRESHOLD:
            return ""
        # Tool-failure taxonomy: the streak the loop guard detected is a
        # learnable pattern, not just an in-run nudge. Persist it (class
        # ``tool_flaky``) so recall warns the next similar goal away from the
        # tool and find_tools can demote it. No-op unless [reflexion] is on.
        try:
            from . import reflexion as _r
            if _r.enabled():
                head = (raw_output or "").strip().splitlines()
                _r.record(
                    goal_text=_r._sanitize_text(self.brief)[:500],
                    failure_class="tool_flaky",
                    failure_msg=(head[0][:200] if head else ""),
                    reflection=(
                        f"The `{name}` tool failed the same way {streak}x in a "
                        "row on this kind of goal. Reach for an alternative "
                        "tool or different arguments early instead of retrying."
                    ),
                    tools_used=[name],
                    domain=self.domain,
                )
        except Exception:  # pragma: no cover -- learning never blocks the loop
            pass
        return (
            f"\n\n[loop-guard] You have issued this exact `{name}` call "
            f"{streak} times in a row and it failed the same way each time. "
            "Do NOT repeat it again — change the arguments, switch tools, or "
            "step back and rethink the approach."
        )

    def _is_parallel_safe(self, name: str) -> bool:
        """Whether ``name`` may execute concurrently with the other tool
        calls in the same turn. Reads the tool's ``parallel_safe`` flag;
        unknown tools (and any tool missing the attribute, e.g. a plugin
        built against an older Tool dataclass) default to False — serial.
        """
        try:
            return bool(getattr(self.tools.get(name), "parallel_safe", False))
        except KeyError:
            return False

    @staticmethod
    def _make_tool_result(tool_use_id: str, output: str) -> dict:
        """Build a tool_result block, flagging errors for the model.

        May 26 council fix (API audit #4): set ``is_error: true`` on
        tool_results that surface an error. Per Anthropic docs, this
        tells Claude the tool failed so it can recover instead of
        treating the error string as a normal output. Our tool registry
        prefixes errors with "ERROR: " and the shield emits
        "BLOCKED by Shield".
        """
        tr: dict = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": output,
        }
        # Frame-aware: `output` is the <tool_output …>-wrapped string, so inspect
        # the content inside it (a leading-ERROR check on the frame is always
        # false -- that bug left is_error unset on every failed tool).
        if _tool_call_failed(output):
            tr["is_error"] = True
        return tr

    def _score_step(
        self,
        *,
        step_index: int,
        tool_name: str | None = None,
        tool_succeeded: bool | None = None,
        is_final: bool = False,
        error: str | None = None,
    ) -> None:
        """Score one step via the PRM and post the result to the blackboard.

        No-op unless a non-Null PRM is configured. Never raises: a scoring
        failure is observability noise, not a reason to fail the agent loop.
        """
        promise = progress = None
        if self._prm_enabled:
            try:
                from .prm import StepContext
                reward = self._prm.score(StepContext(
                    goal_id=self.ctx.goal_id or 0,
                    step_index=step_index,
                    role=self.role,
                    tool_name=tool_name,
                    tool_succeeded=tool_succeeded,
                    is_final=is_final,
                    error=error,
                    prior_step_score=self._last_step_score,
                ))
                promise, progress = reward.promise, reward.progress
                self._last_step_score = reward.promise
                self._promise_window.push(reward.promise)
                self.ctx.blackboard.post(
                    self.name, "prm",
                    f"step={step_index} promise={reward.promise:.2f} "
                    f"progress={reward.progress:+.2f} conf={reward.confidence:.2f}",
                )
            except Exception as e:  # pragma: no cover - PRM must never break the loop
                log.debug("PRM scoring skipped: %s", e)
        # Capture is DECOUPLED from the PRM (Karpathy): cheap and unconditional,
        # a no-op unless [self_improvement] capture is on. A deployment shouldn't
        # need a reward model configured just to record what its agents did.
        self._capture_trajectory_step(
            step_index, tool_name, tool_succeeded, is_final, error, promise, progress)

    def _capture_trajectory_step(self, step_index, tool_name, tool_succeeded,
                                 is_final, error, promise, progress) -> None:
        """Append this step to the governed trajectory store -- the data
        foundation for self-improvement. No-op unless [self_improvement] capture
        is on; best-effort, never raises into the loop."""
        try:
            import time as _t

            from .trajectory_store import TrajectoryStep, capture_step
            capture_step(TrajectoryStep(
                ts=_t.time(), goal_id=int(self.ctx.goal_id or 0),
                episode_id=int(getattr(self.ctx, "episode_id", 0) or 0),
                step=int(step_index), role=self.role, tool=tool_name or "",
                tool_succeeded=tool_succeeded, is_final=bool(is_final),
                error=error or "", promise=promise, progress=progress,
                domain=self.domain or "",
            ))
        except Exception:  # pragma: no cover -- capture must never break the loop
            pass

    def _mirror_live_spend(self, episode_id: int) -> None:
        """Throttled write of running totals onto the open episode row (#614).

        Only the root agent (depth 0) of a goal-scoped run mirrors; sub-agents
        share the goal's single episode and budget, so the orchestrator's
        write already covers the whole swarm's accruing spend. Read-side
        observability only -- `update_episode_spend` guards on
        `ended_at IS NULL` so it can never clobber `end_episode`. Never raises.
        """
        if self.depth != 0 or not episode_id or self.ctx.goal_id is None:
            return
        now = time.monotonic()
        if (now - self._last_spend_mirror) < _SPEND_MIRROR_INTERVAL:
            return
        self._last_spend_mirror = now
        b = self.ctx.budget
        try:
            self.ctx.world.update_episode_spend(
                episode_id,
                cost_dollars=b.dollars,
                input_tokens=b.input_tokens,
                output_tokens=b.output_tokens,
                tool_calls=b.tool_calls,
            )
        except Exception as e:  # pragma: no cover -- observability never blocks
            log.debug("live-spend mirror skipped: %s", e)

    async def run(self) -> AgentResult:
        # OTel GenAI semconv: every agent execution is an ``invoke_agent``
        # span (gen_ai.agent.name/id), the third semconv leg alongside the
        # LLM (chat) and tool (execute_tool) spans. No-op when tracing is off.
        try:
            from .observability import (
                gen_ai_agent_attributes,
                safe_agent_telemetry_label,
                trace_span,
            )
        except Exception:  # pragma: no cover -- tracing never blocks a run
            return await self._run_inner()
        telemetry_role = safe_agent_telemetry_label(self.role)
        with trace_span(
            f"invoke_agent {telemetry_role}",
            attributes=gen_ai_agent_attributes(self.role, agent_id=self.name),
        ):
            return await self._run_inner()

    async def _run_inner(self) -> AgentResult:  # noqa: C901  -- core agent turn loop; decompose only under dedicated review (see below)
        bb = self.ctx.blackboard
        bb.post(self.name, "plan", f"role={self.role} depth={self.depth} brief={self.brief}")

        # Opt-in prompt-cache pre-warm (default OFF). Warm only the orchestrator
        # -- the first, largest, user-facing prompt -- once before its loop, so
        # the first real turn reads the system+tools cache instead of paying the
        # cold-write latency. Subagents are skipped (each has a distinct prompt;
        # warming them would be a wasted write). Never blocks the run.
        if self.role == "orchestrator":
            try:
                from .llm import cache_prewarm_enabled
                if cache_prewarm_enabled():
                    self.ctx.budget.check()
                    self.ctx.llm.prewarm(
                        self.system, self.tools.to_anthropic(), self.model,
                        budget=self.ctx.budget)
            except Exception:  # pragma: no cover -- prewarm never blocks a run
                pass

        # If the goal has image attachments, embed them as vision content
        # blocks on the first user message so the agent can see them.
        # Text/PDF attachments are reachable via `list_attachments` +
        # `read_file` (opt-in so we don't blow token budget on huge PDFs).
        image_blocks: list[dict] = []
        if self.depth == 0 and self.ctx.goal_id is not None:
            try:
                from .attachments import content_blocks_for_goal
                image_blocks = content_blocks_for_goal(
                    self.ctx.world, self.ctx.goal_id,
                )
            except Exception:
                image_blocks = []

        brief_text = (
            f"Sub-goal: {self.brief}\n\n"
            f"Recent swarm activity:\n{bb.render(40) or '(empty)'}\n\n"
            "Plan briefly, then act. End with FINAL: <answer> when done."
        )
        first_content: list[dict] | str
        if image_blocks:
            first_content = image_blocks + [{"type": "text", "text": brief_text}]
        else:
            first_content = brief_text
        messages: list[dict] = [{"role": "user", "content": first_content}]

        # Durable execution (Phase 1): resume a crashed single-agent run from
        # its last committed step instead of re-running from step 0. Off by
        # default, fail-open — any error here leaves `messages`/`start_step`
        # untouched, i.e. today's warm-restart behavior. Scoped to depth-0
        # (the swarm-tree case is Phase 2; see docs/specs/durable-execution.md).
        start_step = 0
        ckpt = None
        ep_id = getattr(self.ctx, "episode_id", 0) or 0
        if self.depth == 0 and self.ctx.goal_id is not None:
            try:
                from . import checkpoint as _ckpt_mod
                if _ckpt_mod.enabled():
                    ckpt = _ckpt_mod.Checkpointer(self.ctx.world)
                    # Resume keys on a STABLE id, not self.name (a per-process
                    # random uuid that never matched on a fresh-process resume).
                    saved = ckpt.latest(
                        self.ctx.goal_id, self.checkpoint_id, episode_id=ep_id,
                    )
                    if saved is not None and saved.messages:
                        messages = saved.messages
                        start_step = saved.step_seq
                        try:
                            self.ctx.budget = _ckpt_mod.restore_budget(saved.budget)
                        except Exception:
                            pass
                        bb.post(self.name, "plan",
                                f"resumed from checkpoint at step {start_step}")
            except Exception as e:  # pragma: no cover -- never block a run
                log.debug("checkpoint resume skipped: %s", e)

        for step in range(start_step, self.max_steps):
            # Durable checkpoint at the turn boundary: commit the resumable
            # loop state (step index, messages, budget snapshot) BEFORE the
            # next LLM call, so a crash mid-step loses at most one step's work.
            # Fail-open: a store error never stops the run.
            if ckpt is not None:
                try:
                    ckpt.save(
                        goal_id=self.ctx.goal_id, agent_id=self.checkpoint_id,
                        episode_id=ep_id, step_seq=step, messages=messages,
                        budget=self.ctx.budget, meta={"role": self.role},
                    )
                except Exception as e:  # pragma: no cover
                    log.debug("checkpoint save skipped: %s", e)

            # Turn-boundary safety gate. Evaluate the global killswitch
            # (`maverick halt`, the dashboard Halt button, or the HALT
            # file) and the wall-clock/token/tool caps BEFORE the next LLM
            # call, so a runaway or over-budget swarm stops promptly
            # instead of only after the next record_* call. killswitch and
            # budget.check() are cheap and side-effect-free.
            try:
                killswitch.check()
                self.ctx.budget.check()
            except killswitch.Halted as e:
                bb.post(self.name, "error", f"halted: {e}")
                return AgentResult(error=f"halted: {e}", role=self.role, name=self.name)
            except BudgetExceeded as e:
                bb.post(self.name, "error", f"budget exceeded: {e}")
                return AgentResult(error=f"budget exceeded: {e}", role=self.role, name=self.name)

            # Long-horizon review checkpoint (opt-in [safety] review_checkpoint):
            # at the root, fire a human-review heartbeat every N dollars / M tool
            # calls / T seconds. A reviewer vote to halt stops the run cleanly,
            # like the killswitch. Inert (no checkpoint object) when unconfigured.
            if self.role == "orchestrator" and self._review_checkpoint is not None:
                _cp_event = self._review_checkpoint.check(self.ctx.budget)
                if _cp_event is not None:
                    bb.post(self.name, "note",
                            f"review checkpoint halted the run at "
                            f"{_cp_event.reason}={_cp_event.value:g}")
                    return AgentResult(
                        error=f"halted at review checkpoint ({_cp_event.reason})",
                        role=self.role, name=self.name)

            # #614 live-spend mirror: at the turn boundary, the root agent
            # writes the budget's running totals onto its open episode row
            # (throttled) so `maverick runs` / `maverick budget` reflect
            # accruing spend mid-run instead of $0.00 until end_episode.
            # Read-side only; never blocks the run.
            self._mirror_live_spend(ep_id)

            # #611 synthesis reserve: a deeper worker yields before it eats the
            # budget the top-level goal needs to write its answer. Only workers
            # (depth > 0) stop here; the orchestrator (depth 0) keeps the reserve
            # to synthesize. Return whatever partial findings we have rather than
            # spending into the reserve, so the run delivers SOMETHING instead of
            # paying in full for nothing.
            if self.depth > 0 and _SYNTHESIS_RESERVE > 0:
                _b = self.ctx.budget
                if _b.dollars >= _b.max_dollars * (1.0 - _SYNTHESIS_RESERVE):
                    bb.post(
                        self.name, "note",
                        f"stopping at ${_b.dollars:.2f}/${_b.max_dollars:.2f} to "
                        f"reserve the final {_SYNTHESIS_RESERVE:.0%} for synthesis",
                    )
                    partial = _last_assistant_text(messages)
                    return AgentResult(
                        final=partial or "(stopped early to reserve synthesis budget)",
                        role=self.role, name=self.name,
                    )

            # Karpathy SOTA-review item: long-context compaction. Drop
            # raw tool_result content >2KiB once it's behind the recent
            # window. The first message (user brief) is always kept.
            # The compaction cost is O(len(messages)) per turn -- cheap
            # vs. paying full-price input tokens for a 100k history.
            # Default path is the heuristic shrink; an operator can opt into a
            # richer strategy via [context] compaction_strategy (heuristic /
            # learned / multimodal / streaming / graph) — all registered in the
            # one compaction_plugins dispatcher, which fails safe to heuristic
            # on an unknown name. The agent's llm seam + conversation id reach
            # the strategies that use them.
            # Process-reward guidance (opt-in, default off): if the PRM has
            # judged the last few steps unpromising, nudge a course-change. A
            # no-op unless [self_improvement] prm_guidance is on AND a PRM is
            # configured, so default behaviour is unchanged.
            from .prm_guidance import maybe_nudge
            _prm_note = maybe_nudge(self._promise_window.values())
            if _prm_note and step - self._last_prm_nudge_step >= 3:
                messages.append({"role": "user", "content": _prm_note})
                self._last_prm_nudge_step = step

            from .compaction_plugins import compact_with
            # Some opt-in strategies make provider calls, so apply the same
            # pre-spend gate and budget object to compaction as the main turn.
            self.ctx.budget.check()
            messages = compact_with(
                messages, llm=self.ctx.llm,
                conversation_id=str(getattr(self.ctx, "goal_id", "") or ""),
                budget=self.ctx.budget,
                scope=self.domain,
            )

            try:
                # Stop BEFORE spending another call when the cap is already
                # hit. record_tokens() only checks AFTER the response lands,
                # so a goal at 99% of budget would otherwise still fire one
                # more (potentially expensive) call.
                self.ctx.budget.check()
                # Pass effort only when configured (None by default) so the call
                # signature is unchanged when the feature is off.
                _effort_kw = {"effort": self.effort} if self.effort else {}
                resp = await self.ctx.llm.complete_async(
                    system=self.system,
                    messages=messages,
                    tools=self.tools.to_anthropic(),
                    budget=self.ctx.budget,
                    max_tokens=4096,
                    thinking_budget=self._thinking_budget(),
                    model=self.model,
                    **_effort_kw,
                )
            except BudgetExceeded as e:
                bb.post(self.name, "error", f"budget exceeded: {e}")
                return AgentResult(error=f"budget exceeded: {e}", role=self.role, name=self.name)

            # May 26 smoke fix: when the response contains BOTH a FINAL:
            # marker AND tool_use blocks, the model is confused. If
            # FINAL validation fails and we `continue`, the tool_use
            # blocks get appended to assistant message history with NO
            # matching tool_result — Anthropic returns HTTP 400 on the
            # next turn:
            #   messages.N: tool_use ids were found without tool_result
            #   blocks immediately after
            # Drop the tool_use blocks before assembling the assistant
            # message; the FINAL critique is what we want the model to
            # respond to, not the orphan tools.
            final_dropped_tools = False
            if resp.text and resp.tool_calls:
                from .coding_mode import has_final_marker as _has_final
                if _has_final(resp.text):
                    resp.tool_calls = []
                    final_dropped_tools = True

            assistant_content: list[dict] = []
            ordered_blocks = getattr(resp, "content_blocks", None)
            if final_dropped_tools:
                # May 28 fix #2: the model emitted a FINAL: marker AND
                # tool_use in the same turn; we discard the tool attempt and
                # treat FINAL as the answer. Do NOT replay the model's blocks
                # here. Dropping the interleaved tool_use would merge
                # previously-separated thinking blocks into one consecutive
                # run, and on a revision pass (verifier/patch reject ->
                # continue) the re-sent turn 400s:
                #   messages.N.content.M: `thinking`/`redacted_thinking`
                #   blocks in the latest assistant message cannot be modified.
                # The tool_use can't stay either (orphan with no
                # tool_result). Omitting thinking from a turn is explicitly
                # allowed (the API auto-filters prior-turn thinking), so emit
                # a clean text-only turn. resp.text is non-empty here (guarded
                # by `resp.text and resp.tool_calls` above).
                assistant_content.append({"type": "text", "text": resp.text})
            elif ordered_blocks:
                # May 28 fix: replay the model's blocks in their ORIGINAL
                # order, COMPLETE and UNMODIFIED. Anthropic rejects a
                # rearranged thinking-block sequence on the next request —
                # the bucket-by-type rebuild in the else branch reordered
                # interleaved Opus 4.7 turns (thinking between tool_use) and
                # triggered "thinking blocks in the latest assistant message
                # cannot be modified". (The only tool_use-dropping case,
                # FINAL, is handled above — here every block is kept so the
                # tool_use blocks always have matching tool_results below.)
                for blk in ordered_blocks:
                    assistant_content.append(dict(blk))
            else:
                # May 26 council fix: emit ONE thinking block per original
                # block, preserving each block's exact signature. Concatenating
                # text but keeping only the first signature corrupted multi-
                # block interleaved thinking on Opus 4.7 — the signature is
                # derived from the EXACT text of its block. Falls back to
                # the legacy single-block path when thinking_blocks is empty
                # but resp.thinking is set (older mocks / non-Anthropic).
                thinking_blocks = getattr(resp, "thinking_blocks", None) or []
                if thinking_blocks:
                    # May 26 council fix (API audit #2): include the block
                    # EVEN IF the text is empty as long as a signature is
                    # present. Anthropic still requires the signature-bearing
                    # block to be echoed back to maintain continuity. The old
                    # `if resp.thinking:` check at the elif below would drop
                    # empty-text-signature pairs entirely.
                    for tb_text, tb_sig in thinking_blocks:
                        if not tb_text and not tb_sig:
                            continue
                        block_dict: dict = {"type": "thinking", "thinking": tb_text}
                        if tb_sig:
                            block_dict["signature"] = tb_sig
                        assistant_content.append(block_dict)
                elif resp.thinking or getattr(resp, "thinking_signature", None):
                    sig = getattr(resp, "thinking_signature", None)
                    thinking_block: dict = {
                        "type": "thinking", "thinking": resp.thinking or "",
                    }
                    if sig:
                        thinking_block["signature"] = sig
                    assistant_content.append(thinking_block)
                if resp.text:
                    assistant_content.append({"type": "text", "text": resp.text})
                for tc in resp.tool_calls:
                    assistant_content.append(
                        {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
                    )
            messages.append({"role": "assistant", "content": assistant_content})

            if resp.text:
                # Wave 12 hotfix: the prompt instructs the model to "End
                # your turn with `FINAL:`" — many models emit a brief
                # reasoning line BEFORE FINAL: (e.g. "Target: foo.py:bar
                # — fix is X. FINAL: ..."). The prior `startswith` check
                # missed those entirely; the SR block went to the
                # blackboard as a plain observation, was never applied,
                # and the orchestrator returned the raw SR text as
                # `final` with `final_patch=None` — silent score loss.
                # Use the LAST line-anchored FINAL: marker OUTSIDE any
                # fenced code block. Skipping code-block markers
                # prevents attacker-controlled quoted content (file
                # bodies, tool output) from redefining the final
                # answer mid-response.
                from .coding_mode import find_final_marker_end as _final_end
                _fe = _final_end(resp.text)
                if _fe is not None:
                    final = resp.text[_fe:].strip()
                    # May 26 council fix: clear any stale `_final_patch`
                    # from a previous FINAL attempt. If a prior FINAL was
                    # rejected (defensive/validate) and the revised
                    # FINAL has no apply-check (because _patch_validated
                    # was True), the verifier/return branches would read
                    # the STALE patch from the earlier FINAL and submit
                    # it — wrong patch attribution.
                    self._final_patch = None
                    # May 26 council fix (agent-loop audit #4): also
                    # clear `_already_verified` so the revised FINAL
                    # gets verified afresh. Without this, a rejected
                    # FINAL's `_already_verified=True` flag would skip
                    # the verifier on the revised FINAL — and the
                    # revised version would return with
                    # `verifier_confidence=1.0` (the fallback when
                    # verdict is None) regardless of actual quality.
                    self._already_verified = False
                    # #612: `_patch_validated` was sticky for the whole run
                    # (only ever set True), so after one rejected patch a
                    # later genuinely-different FINAL would skip its own
                    # apply-check / diff extraction. Reset it alongside
                    # `_already_verified` so each new FINAL re-validates the
                    # patch it actually carries.
                    self._patch_validated = False

                    # Wave 8: coding-mode patch self-validation. If the
                    # workdir is a git repo AND the FINAL contains a
                    # unified diff, run `git apply --check` BEFORE
                    # declaring FINAL. A rejected patch loops back with
                    # the git error as critique -- catches the
                    # ~30% of SWE-bench failures that are unapplyable
                    # patches without burning a verifier round.
                    coding_cfg = None
                    try:
                        from .coding_mode import (
                            from_env as _cm_from_env,
                        )
                        from .coding_mode import (
                            validate_patch,
                        )
                        coding_cfg = _cm_from_env()
                    except Exception:
                        pass

                    if (coding_cfg is not None and coding_cfg.enabled
                            and coding_cfg.require_apply_check
                            and not getattr(self, "_patch_validated", False)):
                        from pathlib import Path as _Path
                        workdir = _Path(getattr(self.ctx.sandbox, "workdir", "."))
                        # Wave 11: prefer SEARCH/REPLACE over unified-diff.
                        from .edit_format import repair_prompt_for_failure
                        # Serialize the apply->reset on the SHARED sandbox.workdir
                        # with the same lock the verifier branch below uses.
                        # require_apply_check runs for every coding-mode agent
                        # regardless of depth/role, so concurrent coder children
                        # under spawn_swarm would otherwise interleave apply +
                        # `git reset --hard` on one git tree and corrupt each
                        # other's edits. (Sequential with the verifier branch's
                        # own `async with`, so no nested/reentrant acquire.)
                        async with self.ctx.workdir_lock:
                            # Offload blocking git/subprocess work to a thread so
                            # it doesn't stall the event loop (freezing every other
                            # concurrent sub-agent, the channel server, and the
                            # dashboard) while the lock is held. Mirrors the
                            # asyncio.to_thread wrap in tools/agent_bus_tool.py.
                            patch, sr_summary = await asyncio.to_thread(
                                self._extract_and_apply_patch, final)
                            # Reset workdir AFTER capturing the diff so the
                            # verifier branch (and downstream evaluators) see
                            # HEAD when they re-apply.
                            if sr_summary is not None:
                                await asyncio.to_thread(self._reset_workdir)
                                try:
                                    self.ctx.blackboard.post(
                                        self.name, "tool_signal",
                                        "search_replace_used=1",
                                    )
                                except Exception:
                                    pass
                        if patch is None and sr_summary is not None:
                            self._patch_validated = True
                            bb.post(
                                self.name, "verify",
                                f"SEARCH/REPLACE apply failed: "
                                f"{sr_summary.summary_text()}",
                            )
                            first_fail = next(
                                (r for r in sr_summary.results if not r.ok),
                                None,
                            )
                            critique = (
                                "Your FINAL SEARCH/REPLACE block(s) did "
                                "not apply.\n\n" + sr_summary.summary_text()
                            )
                            if first_fail is not None:
                                critique += "\n\n" + repair_prompt_for_failure(
                                    first_fail,
                                )
                            messages.append({"role": "user", "content": critique})
                            continue
                        if patch is None:
                            self._patch_validated = True
                            bb.post(
                                self.name, "verify",
                                "no valid SEARCH/REPLACE or unified diff in "
                                "FINAL; asking for revision",
                            )
                            messages.append({
                                "role": "user",
                                "content": (
                                    "Your FINAL did not contain valid edits. "
                                    "Use SEARCH/REPLACE format (preferred):\n\n"
                                    "path/to/file.py\n"
                                    "<<<<<<< SEARCH\n"
                                    "<exact existing lines>\n"
                                    "=======\n"
                                    "<new lines>\n"
                                    ">>>>>>> REPLACE\n\n"
                                    "Multiple blocks allowed, each can target "
                                    "a different file. Or as a fallback, a "
                                    "unified diff in ```diff fences."
                                ),
                            })
                            continue
                        # Stash the rendered patch so the verifier branch
                        # doesn't have to re-parse.
                        self._final_patch = patch
                        # Wave 11: defensive validation BEFORE git apply
                        # --check. Catches grader-fatal patches (test
                        # files, dep pins, cheating-detector overlap)
                        # so we ask for revision instead of submitting
                        # something the grader will silently zero out.
                        try:
                            from .coding_mode import (
                                defensive_validate,
                                get_gold_patch,
                            )
                            def_check = defensive_validate(
                                patch,
                                fail_to_pass=coding_cfg.fail_to_pass,
                                pass_to_pass=coding_cfg.pass_to_pass,
                                gold_patch=get_gold_patch(),
                                opaque=(os.environ.get(
                                    "MAVERICK_BENCHMARK_OPAQUE", "1",
                                ) != "0"),
                            )
                        except Exception:
                            def_check = None
                        if def_check is not None and not def_check.ok:
                            # May 26 smoke fix: DO NOT set
                            # `_patch_validated = True` here. The flag
                            # short-circuits the entire SR-extract-apply
                            # block on the next iteration, so when the
                            # agent revises in response to the critique,
                            # the new SR blocks are silently ignored
                            # (workdir untouched, no patch produced).
                            # Fired on pallets/flask-5014 — agent
                            # produced correct fix, cheating detector
                            # false-positive rejected it, then the
                            # agent's revision attempt was no-op'd.
                            bb.post(
                                self.name, "verify",
                                f"patch rejected by defensive validator: "
                                f"{def_check.blocked_paths or def_check.warnings}",
                            )
                            messages.append({
                                "role": "user",
                                "content": def_check.critique(),
                            })
                            continue
                        # Wave 12 hardening: when defensive validate
                        # passes (ok=True) but emitted warnings (WARN
                        # path — conftest.py / pyproject.toml etc.),
                        # post the advisory to the blackboard so it
                        # shows up in trace; we still ACCEPT the patch.
                        if def_check is not None and def_check.warnings:
                            bb.post(
                                self.name, "verify",
                                f"defensive warnings (accepted anyway): "
                                f"{def_check.warnings}",
                            )
                        validation = validate_patch(patch, workdir)
                        if not validation.valid:
                            self._patch_validated = True  # one retry max
                            bb.post(
                                self.name, "verify",
                                f"patch rejected: {validation.reason}",
                            )
                            messages.append({
                                "role": "user",
                                "content": (
                                    "Your FINAL patch did not pass "
                                    "`git apply --check`.\n\n"
                                    f"Reason: {validation.reason}\n\n"
                                    f"git stderr:\n{validation.git_apply_stderr}\n\n"
                                    "Re-examine the exact line content via "
                                    "`read_file`, fix the edits, and respond "
                                    "with a new FINAL using SEARCH/REPLACE "
                                    "blocks (preferred) or a unified diff."
                                ),
                            })
                            continue

                    # Karpathy SOTA-review item: verifier role exists in
                    # prompt strings only -- no code actually runs a
                    # second-pass check. Now we do, but only on the
                    # orchestrator's FINAL (depth=0) and only once per
                    # goal. Sub-agents skip verification (their parent
                    # is the verifier of last resort).
                    verdict = None
                    # Set True once verify_final actually runs, so a verifier
                    # that hits the budget (verdict stays None) is distinguished
                    # from a role that never verifies -- see the FINAL return.
                    verifier_attempted = False
                    # Risk-proportional verification (opt-in): set True when the
                    # orchestrator deems the FINAL low-risk and skips the LLM
                    # verifier. Distinct from "attempted but did not complete".
                    verification_skipped = False
                    # Only the orchestrator's FINAL is verified. Sub-agents
                    # answer to their parent; the parent is their verifier.
                    if (
                        self.role == "orchestrator"
                        and self.depth == 0
                        and not getattr(self, "_already_verified", False)
                        and self.ctx.goal_id is not None
                    ):
                        # Wave 8: when SWE-bench-style ground-truth tests
                        # are provided, run them as the verifier instead
                        # of (or alongside) the LLM judge. Ground truth
                        # >> opinion; this is how OpenHands gets to 72%.
                        if (coding_cfg is not None and coding_cfg.enabled
                                and (coding_cfg.fail_to_pass or coding_cfg.pass_to_pass)):
                            async with self.ctx.workdir_lock:
                                from pathlib import Path as _Path

                                from .coding_mode import run_failing_tests
                                workdir = _Path(getattr(self.ctx.sandbox, "workdir", "."))
                                # Wave 11: reuse the patch produced by the
                                # validate branch above (SEARCH/REPLACE or
                                # unified-diff). If the validate branch was
                                # skipped (e.g. require_apply_check=False),
                                # extract here.
                                patch = getattr(self, "_final_patch", None)
                                if patch is None:
                                    patch, _ = await asyncio.to_thread(
                                        self._extract_and_apply_patch, final)
                                    if patch is not None:
                                        # We applied to disk; reset for the
                                        # verifier's own apply.
                                        await asyncio.to_thread(self._reset_workdir)
                                if patch is None:
                                    if not getattr(self, "_patch_validated", False):
                                        self._patch_validated = True
                                        bb.post(
                                            self.name, "verify",
                                            "no valid diff in FINAL; asking for revision",
                                        )
                                        messages.append({
                                            "role": "user",
                                            "content": (
                                                "Your FINAL did not contain valid "
                                                "edits. Use SEARCH/REPLACE blocks "
                                                "(preferred) or a unified diff in "
                                                "```diff fences."
                                            ),
                                        })
                                        continue
                                    # Already revised once; surface and exit.
                                    return AgentResult(
                                        final=final, role=self.role, name=self.name,
                                        verifier_confidence=0.0,
                                        verifier_critique="no valid diff in FINAL",
                                    )

                                apply_ok = await asyncio.to_thread(self._git_apply, patch)

                                # Wave 10 (D10): only run tests when apply
                                # succeeded. Running tests on HEAD when apply
                                # failed wastes a full test run (minutes on
                                # SWE-bench), reports all FAIL_TO_PASS as
                                # failing for the wrong reason, then misleads
                                # the revision pass.
                                if not apply_ok:
                                    test_result = None  # type: ignore[assignment]
                                else:
                                    try:
                                        # run_failing_tests shells out to pytest --
                                        # minutes on SWE-bench. Off-load it so the
                                        # whole event loop isn't frozen for the
                                        # duration.
                                        test_result = await asyncio.to_thread(
                                            run_failing_tests,
                                            workdir,
                                            coding_cfg.fail_to_pass,
                                            coding_cfg.pass_to_pass,
                                            self.ctx.sandbox,
                                            language=coding_cfg.language,
                                        )
                                    finally:
                                        # Always revert the workdir so the next
                                        # attempt reads HEAD, not the post-patch
                                        # tree. Without this, successive
                                        # revisions see corrupted state and
                                        # compound the error.
                                        await asyncio.to_thread(self._reset_workdir)

                                if not apply_ok:
                                    # Wave 10 (D10): tests were skipped because
                                    # the patch wouldn't apply. Tell the agent
                                    # so it doesn't 'fix' a working patch into
                                    # a broken one based on apply-fail noise.
                                    if not getattr(self, "_patch_validated", False):
                                        self._patch_validated = True
                                        bb.post(
                                            self.name, "verify",
                                            "patch failed to apply pre-test; "
                                            "asking proposer to revise",
                                        )
                                        messages.append({
                                            "role": "user",
                                            "content": (
                                                "Your patch could not be applied "
                                                "via `git apply`. Re-examine the "
                                                "current file contents with "
                                                "`read_file` and produce a fresh "
                                                "unified diff against HEAD."
                                            ),
                                        })
                                        continue
                                    # Already retried once; surface and exit.
                                    return AgentResult(
                                        final=final, role=self.role, name=self.name,
                                        verifier_confidence=0.0,
                                        verifier_critique="patch did not apply",
                                    )

                                bb.post(
                                    self.name, "verify",
                                    f"test-driven verifier: {test_result.summary()}",
                                )
                                # Calibration auto-collection: tests are GROUND
                                # TRUTH here, so also ask the LLM verifier and
                                # record (confidence, correct) -- this is how the
                                # calibration interlock learns whether the judge
                                # still tracks reality. Opt-in (one extra verifier
                                # call) + fail-open.
                                try:
                                    from . import calibration
                                    if calibration.collect_from_coding_enabled():
                                        from .verifier import verify_proposal
                                        _cv = await verify_proposal(
                                            self.brief, final, self.ctx.llm,
                                            self.ctx.budget, proposer_model=self.model,
                                        )
                                        calibration.record_sample(
                                            _cv.confidence, test_result.all_pass,
                                            source="coding",
                                        )
                                except Exception:  # pragma: no cover -- never break the loop
                                    pass
                                if test_result.all_pass:
                                    # Tests pass → accept FINAL. Skip LLM verifier.
                                    self._already_verified = True
                                    return AgentResult(
                                        final=final, role=self.role, name=self.name,
                                        verifier_confidence=test_result.score,
                                        verifier_critique=test_result.summary(),
                                        final_patch=getattr(self, "_final_patch", None),
                                    )
                                # Tests failed → revise. Wave 9 (council H2):
                                # do NOT leak raw assertion bodies to the
                                # agent in benchmark mode -- that's a recipe
                                # for hardcoding to the test's expected value.
                                # Wave 11 (PROBE-lite): classify the failure
                                # type and surface a targeted hint without
                                # leaking expected values.
                                opaque = os.environ.get("MAVERICK_BENCHMARK_OPAQUE", "1") != "0"
                                from .coding_mode import classify_failure
                                fail_class, fail_hint = classify_failure(
                                    test_result.raw_output,
                                )
                                class_line = (
                                    f"Dominant failure class: {fail_class}.\n{fail_hint}"
                                    if fail_class != "other" else ""
                                )
                                if opaque:
                                    critique = (
                                        "Your patch did not pass the required tests.\n\n"
                                        f"{test_result.summary()}\n\n"
                                        f"{class_line}\n\n"
                                        "Revise based on your understanding of the "
                                        "code, not from inspecting the failing "
                                        "tests' expected values. Respond with a "
                                        "new FINAL using SEARCH/REPLACE blocks."
                                    ).strip()
                                else:
                                    critique = (
                                        "Your patch did not pass the required tests.\n\n"
                                        f"{test_result.summary()}\n\n"
                                        f"{class_line}\n\n"
                                        f"Recent test output:\n{test_result.raw_output}\n\n"
                                        "Inspect the failing tests, revise your patch, "
                                        "and respond with a new FINAL using "
                                        "SEARCH/REPLACE blocks."
                                    ).strip()
                                # Wave 9 fix (#2): one retry max so a flaky
                                # verifier or unfixable instance doesn't loop
                                # forever. The retry IS re-verified.
                                if getattr(self, "_patch_validated", False):
                                    # Already revised once; accept whatever this is.
                                    self._already_verified = True
                                    return AgentResult(
                                        final=final, role=self.role, name=self.name,
                                        verifier_confidence=test_result.score,
                                        verifier_critique=test_result.summary(),
                                        final_patch=getattr(self, "_final_patch", None),
                                    )
                                self._patch_validated = True
                                messages.append({"role": "user", "content": critique})
                                continue

                        if (
                            _risk_proportional_verify_enabled()
                            and _final_is_low_risk(
                                final,
                                coding=bool(coding_cfg and coding_cfg.enabled),
                                tool_calls=self.ctx.budget.tool_calls,
                            )
                        ):
                            verification_skipped = True
                            bb.post(
                                self.name, "verify",
                                "verification skipped (risk-proportional: "
                                "low-risk answer, no tools/code)",
                            )
                        else:
                            try:
                                from .verifier import verify_final
                                verifier_attempted = True
                                # Loop 1: a high-disagreement swarm fan-out asks
                                # FINAL to face the cross-family ensemble.
                                verdict = await verify_final(
                                    self.brief, final, self.ctx.llm, self.ctx.budget,
                                    proposer_model=self.model,
                                    force_ensemble=bool(
                                        getattr(self.ctx, "escalate_verification", False)
                                    ),
                                )
                                # Stamp the verdict so the autonomy servo (Loop 2)
                                # can tighten the leash on low-confidence runs.
                                self.ctx.last_verifier_confidence = verdict.confidence
                            except BudgetExceeded:
                                verdict = None
                            except Exception as e:  # pragma: no cover
                                bb.post(self.name, "error", f"verifier failed: {e}")
                                verdict = None

                        if verdict is not None and not verdict.accepts:
                            if getattr(self, "_verifier_revision_used", False):
                                self._already_verified = True
                                bb.post(
                                    self.name, "verify",
                                    "verifier rejected after retry; accepting "
                                    "second attempt per one-revision cap",
                                )
                                _reasons = _final_uncertainty_reasons(
                                    verifier_rejected=True,
                                    verifier_incomplete=False,
                                    disagreement=float(
                                        getattr(self.ctx, "last_disagreement", 0.0) or 0.0
                                    ),
                                    coding=bool(coding_cfg and coding_cfg.enabled),
                                )
                                return AgentResult(
                                    final=_final_with_uncertainty_note(final, _reasons),
                                    role=self.role, name=self.name,
                                    verifier_confidence=verdict.confidence,
                                    verifier_critique=verdict.critique,
                                    final_patch=getattr(self, "_final_patch", None),
                                )
                            self._already_verified = True
                            self._verifier_revision_used = True
                            bb.post(
                                self.name, "verify",
                                f"verifier rejected (conf={verdict.confidence:.2f}): "
                                f"{verdict.critique}",
                            )
                            # Hand the critique to the proposer as a
                            # revision brief. One revision pass max --
                            # the second attempt is accepted regardless.
                            issues_block = (
                                "\n".join(f"  - {i}" for i in verdict.issues)
                                if verdict.issues else "  (no specific issues listed)"
                            )
                            messages.append({
                                "role": "user",
                                "content": (
                                    "A verifier rejected your FINAL answer. "
                                    "Revise and try again.\n\n"
                                    f"Verifier confidence: {verdict.confidence:.2f}\n"
                                    f"Critique: {verdict.critique}\n"
                                    f"Specific issues:\n{issues_block}\n\n"
                                    "Address each issue and respond with a "
                                    "new FINAL: <revised answer>."
                                ),
                            })
                            continue
                        if verdict is not None:
                            bb.post(
                                self.name, "verify",
                                f"verifier accepted (conf={verdict.confidence:.2f})",
                            )

                    bb.post(self.name, "finding", final)
                    self.ctx.world.append_message(
                        self.ctx.goal_id, f"agent:{self.name}", final
                    )
                    # Stop hooks: the agent has decided on FINAL. Post-style
                    # (non-blocking) -- observers/loggers, cannot veto.
                    from .hooks import HookEvent
                    from .hooks import emit as _emit_hook
                    await _emit_hook(
                        HookEvent.STOP,
                        goal_id=self.ctx.goal_id, agent_role=self.role,
                        extra={"name": self.name, "final": final},
                    )
                    self._score_step(step_index=step, is_final=True)
                    if verification_skipped:
                        _vconf, _vcrit = 0.9, (
                            "verification skipped (risk-proportional: low-risk answer)"
                        )
                    elif verdict is not None:
                        _vconf, _vcrit = verdict.confidence, verdict.critique
                    elif verifier_attempted:
                        # Attempted but hit budget/error (verdict is None) must
                        # NOT report high confidence: a budget-starved run would
                        # otherwise be donated as a "high-confidence" trajectory
                        # it never verified (#612).
                        _vconf, _vcrit = 0.0, "verifier did not complete (budget)"
                    else:
                        # Roles that never verify keep the 1.0 default.
                        _vconf, _vcrit = 1.0, ""
                    _reasons = _final_uncertainty_reasons(
                        verifier_rejected=False,
                        verifier_incomplete=(verdict is None and verifier_attempted),
                        disagreement=float(
                            getattr(self.ctx, "last_disagreement", 0.0) or 0.0
                        ),
                        coding=bool(coding_cfg and coding_cfg.enabled),
                    )
                    return AgentResult(
                        final=_final_with_uncertainty_note(final, _reasons),
                        role=self.role, name=self.name,
                        verifier_confidence=_vconf,
                        verifier_critique=_vcrit,
                        final_patch=getattr(self, "_final_patch", None),
                    )
                bb.post(self.name, "observation", resp.text[:1000])

            if not resp.tool_calls:
                if resp.text:
                    return AgentResult(final=resp.text, role=self.role, name=self.name)
                return AgentResult(
                    error="empty response with no tools", role=self.role, name=self.name
                )

            # Tool-call boundary: honour a halt that arrived while the
            # model was producing this turn (e.g. the user hit Halt
            # during a long think) before executing any tool.
            try:
                killswitch.check()
            except killswitch.Halted as e:
                bb.post(self.name, "error", f"halted: {e}")
                return AgentResult(
                    error=f"halted: {e}", role=self.role, name=self.name,
                )

            # Frontier-loop optimization: when the model emits 2+ tool
            # calls in one turn and EVERY one is parallel-safe (pure,
            # idempotent reads — read_file / list_dir / repo_map /
            # dep_graph), run them concurrently with asyncio.gather. This
            # is the dominant localization pattern ("read these 5 files")
            # and collapses N serial awaits into one round-trip's worth of
            # latency. A turn containing ANY stateful tool (shell, write,
            # spawn, ask_user, a rate-limited network tool) falls through
            # to the serial path below, so side-effect ordering and the
            # ask_user block-on-user semantics are unchanged. Disable with
            # MAVERICK_PARALLEL_TOOLS=0.
            run_parallel = (
                len(resp.tool_calls) > 1
                and os.environ.get("MAVERICK_PARALLEL_TOOLS", "1") != "0"
                and all(self._is_parallel_safe(tc.name) for tc in resp.tool_calls)
            )

            tool_results: list[dict] = []
            blocked = False

            def _answer_pending_tool_uses(
                reason: str,
                *,
                resp=resp,
                messages=messages,
                tool_results=tool_results,
            ) -> None:
                # #612: a control-flow stop (BudgetExceeded / Halted) can fire
                # mid-dispatch -- most often from budget.record_tool_call(),
                # which calls check() and can raise AFTER the assistant turn's
                # tool_use blocks are already in `messages`. If we unwind now,
                # the saved/resumed history (or a parent that keeps these
                # messages) has tool_use ids with no matching tool_result ->
                # Anthropic 400 on the next call. Append an error tool_result
                # for every still-unanswered tool_use, then let the caller
                # re-raise/return so the stop is NOT swallowed.
                answered = {tr["tool_use_id"] for tr in tool_results}
                pending = [tc for tc in resp.tool_calls if tc.id not in answered]
                if not pending:
                    return
                for tc in pending:
                    tool_results.append(self._make_tool_result(tc.id, reason))
                messages.append({"role": "user", "content": tool_results})

            if run_parallel:
                import asyncio as _asyncio
                # Account every call up front; record_tool_call mirrors
                # the serial path (one per tool, same count). A budget trip
                # here raises BEFORE any tool ran -- answer every pending
                # tool_use so the turn isn't left with orphan tool_use blocks.
                try:
                    for _tc in resp.tool_calls:
                        self.ctx.budget.record_tool_call()
                except BudgetExceeded:
                    _answer_pending_tool_uses(
                        "ERROR: tool not executed (budget exceeded)"
                    )
                    raise

                # Per-host concurrency cap (#434): same-host network reads in
                # this turn are throttled by a semaphore so a fan-out of reads
                # to one host can't hammer it / trip its rate limit; local and
                # cross-host calls stay fully concurrent (no-op context).
                from . import net_concurrency as _netcc

                async def _run_capped(tc):
                    async with _netcc.limit(tc.name, tc.input):
                        return await self._run_tool(tc.name, tc.input)

                # return_exceptions=True: tools.run swallows its own errors, but
                # the shield scan / PreToolUse hooks inside _run_tool can still
                # raise. Without this, one such raise propagates out of gather,
                # discards the sibling results, and leaves the assistant turn's
                # tool_use blocks with no matching tool_results -> the next API
                # call 400s. Convert a raised exception into an error
                # tool_result so every tool_use is still answered -- but
                # re-raise control-flow signals (budget/halt) so a stop isn't
                # silently downgraded to a tool error.
                outputs = await _asyncio.gather(
                    *(_run_capped(tc) for tc in resp.tool_calls),
                    return_exceptions=True,
                )
                from . import killswitch as _ks
                from .budget import BudgetExceeded as _BE
                _norm: list[str] = []
                for o in outputs:
                    if isinstance(o, (_BE, _ks.Halted)):
                        # #612: re-raise as a stop, but first answer every
                        # tool_use this turn emitted so the history isn't left
                        # with orphan tool_use blocks for a resume/parent.
                        _answer_pending_tool_uses(
                            f"ERROR: tool not executed ({type(o).__name__})"
                        )
                        raise o
                    _norm.append(
                        o if isinstance(o, str)
                        else f"ERROR: tool raised {type(o).__name__}: {o}"
                    )
                outputs = _norm
                # Preserve original call order in the results (matched by
                # tool_use_id, but ordering keeps traces readable).
                for tc, output in zip(resp.tool_calls, outputs, strict=False):
                    bb.post(
                        self.name, "observation",
                        f"tool={tc.name} -> {output[:500]}",
                    )
                    self._score_step(
                        step_index=step,
                        tool_name=tc.name,
                        tool_succeeded=not _tool_call_failed(output),
                    )
                    tool_results.append(self._make_tool_result(tc.id, output))
            else:
                for tc in resp.tool_calls:
                    # Per-tool halt check: a serial turn may run a long
                    # shell command; honour a halt that lands mid-turn.
                    try:
                        killswitch.check()
                    except killswitch.Halted as e:
                        # #612: answer any tool_use we've already passed (and
                        # this + remaining ones) so the assistant turn isn't
                        # left with orphan tool_use blocks before we unwind.
                        _answer_pending_tool_uses("ERROR: tool not executed (halted)")
                        bb.post(self.name, "error", f"halted: {e}")
                        return AgentResult(
                            error=f"halted: {e}", role=self.role, name=self.name,
                        )
                    # #612: record_tool_call() calls check() and can raise
                    # mid-turn; answer pending tool_use blocks, then re-raise
                    # so the budget trip still stops the run cleanly.
                    try:
                        self.ctx.budget.record_tool_call()
                    except BudgetExceeded:
                        _answer_pending_tool_uses(
                            "ERROR: tool not executed (budget exceeded)"
                        )
                        raise
                    # #612: a stateful serial tool (notably `spawn_subagent`,
                    # whose child shares this Budget) can trip BudgetExceeded
                    # — or a halt can land — DURING execution. That raise would
                    # leave this tool_use + any siblings already dispatched this
                    # turn without matching tool_results -> Anthropic 400 on a
                    # resume/parent. Answer every pending tool_use, then re-raise
                    # so the stop still halts the run cleanly.
                    try:
                        output = await self._run_tool(tc.name, tc.input)
                    except (BudgetExceeded, killswitch.Halted):
                        _answer_pending_tool_uses(
                            "ERROR: tool not executed (run stopped)"
                        )
                        raise
                    if tc.name == "ask_user":
                        blocked = True
                    bb.post(
                        self.name, "observation",
                        f"tool={tc.name} -> {output[:500]}",
                    )
                    self._score_step(
                        step_index=step,
                        tool_name=tc.name,
                        tool_succeeded=not _tool_call_failed(output),
                    )
                    tool_results.append(self._make_tool_result(tc.id, output))

            # Step-budget awareness: when only a few tool-using turns remain
            # before max_steps force-stops the run, tell the model so it
            # synthesizes a FINAL now instead of starting new work and getting
            # cut off with no answer. Appended after the tool_results (text
            # after tool_result blocks is a valid user turn); only on turns that
            # ran tools, which is exactly when a working agent risks the cutoff.
            remaining = self.max_steps - 1 - step
            if tool_results and _STEP_BUDGET_WARNING and 0 < remaining <= _STEP_BUDGET_WARNING:
                tool_results.append({
                    "type": "text",
                    "text": (
                        f"⚠ Step budget almost exhausted: about {remaining} more "
                        "tool-using turn(s) remain before this run is force-stopped. "
                        "Prioritize giving your FINAL: answer now with the best "
                        "result you have rather than starting new work."
                    ),
                })
            messages.append({"role": "user", "content": tool_results})

            if blocked:
                return AgentResult(blocked_on_user=True, role=self.role, name=self.name)

        # Wave 12 hotfix: when the agent loop exhausts max_steps without
        # emitting FINAL, the workdir may STILL contain edits made via
        # `str_replace_editor` (the secondary tool channel). The May 26
        # smoke surfaced 3/6 instances where the agent edited via the
        # tool but never produced a FINAL — those instances reported
        # `no-diff` even though the patch was already on disk.
        # Salvage that work by rendering the workdir as the final_patch
        # if there are uncommitted changes.
        try:
            from pathlib import Path as _Path

            from .edit_format import render_diff
            workdir = _Path(getattr(self.ctx.sandbox, "workdir", "."))
            if (workdir / ".git").exists():
                rendered = render_diff(workdir)
                if rendered and rendered.strip():
                    return AgentResult(
                        error=f"hit max_steps={self.max_steps}; "
                              "captured workdir diff as final_patch",
                        final_patch=rendered,
                        role=self.role,
                        name=self.name,
                    )
        except Exception:
            pass
        return AgentResult(
            error=f"hit max_steps={self.max_steps}",
            role=self.role,
            name=self.name,
        )
