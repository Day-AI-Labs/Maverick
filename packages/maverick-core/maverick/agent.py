"""Recursive async agent.

v0.1.4: appends ``persona.render_persona_prompt()`` to the system
prompt of every agent so users can give the swarm a name and voice
without patching the kernel.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets as _secrets
import time
import uuid
from dataclasses import dataclass

from . import killswitch
from ._envparse import env_float, env_int
from .budget import BudgetExceeded
from .llm import model_for_role
from .swarm import SwarmContext
from .tools import ToolRegistry, base_registry
from .tools.agent_bus_tool import recv_from_agent, send_to_agent
from .tools.spawn import spawn_subagent_tool, spawn_swarm_tool

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
    ):
        self.ctx = ctx
        self.role = role
        self.brief = brief
        self.depth = depth
        self.parent = parent
        # Wave 11: Scale Labs' Pro empirical study (arxiv 2509.16941)
        # shows "most successful solutions resolve in ~25 rounds; long-
        # tail iteration past that has diminishing returns." Allow ops
        # to override globally via MAVERICK_MAX_STEPS, default 25.
        self.max_steps = env_int("MAVERICK_MAX_STEPS", max_steps)
        self.name = f"{role}-{depth}-{uuid.uuid4().hex[:6]}"

        self.tools = self._build_tools()
        self.system = self._build_system()
        self.model = model_override or model_for_role(role)
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
        # Live-spend mirror throttle (#614): the root agent periodically
        # mirrors running totals onto its open episode row so `maverick runs`
        # / `maverick budget` reflect accruing mid-run spend instead of
        # $0.00 / 0 tools. Throttled to once per _SPEND_MIRROR_INTERVAL s.
        self._last_spend_mirror = 0.0
        # Loop guard: per-(tool,args) consecutive-failure streak. Grows while an
        # identical call keeps failing; reset when that call finally succeeds.
        self._tool_fail_streak: dict[str, int] = {}

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
        )
        # Cross-agent bus tools, bound to this agent's id so send records
        # the right sender and recv drains the right inbox.
        reg.register(send_to_agent(self.name))
        reg.register(recv_from_agent(self.name))
        if self.depth < self.ctx.max_depth:
            reg.register(spawn_subagent_tool(self))
            reg.register(spawn_swarm_tool(self))
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

        # Skills from prior runs (existing logic).
        if self.ctx.use_skills:
            try:
                from .skills import load_skills, relevant_skills, render_for_prompt
                skills = relevant_skills(self.brief, load_skills())
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

        # Cross-session memory (root agent only): surface the agent's long-term
        # memory index so each run starts with what it learned in earlier
        # sessions -- the long-horizon continuity layer. Mirrors skill
        # injection; the agent pulls file detail on demand via the `memory`
        # tool. Empty memory -> "" -> no change. Depth-gated so deep workers
        # keep lean, focused context (they can still use the tool directly).
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
        if self.role in ("orchestrator", "revisor"):
            return 8000
        return None

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
                rel = _os.path.basename(tmp_path)
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

    async def _run_tool(self, name: str, args: dict) -> str:
        shield = self.ctx.shield
        if shield is not None:
            verdict = shield.scan_tool_call(name, args)
            if not verdict.allowed:
                self.ctx.blackboard.post(
                    self.name, "error",
                    f"tool={name} BLOCKED by Shield: {'; '.join(verdict.reasons)}",
                )
                return (
                    f"⚠ BLOCKED by Shield ({verdict.severity}): "
                    f"{'; '.join(verdict.reasons)}. The tool was not executed."
                )

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

    def _loop_guard_note(self, name: str, args: dict, raw_output: str) -> str:
        """Track this call's outcome; return a nudge when an identical call has
        failed the same way ``_LOOP_GUARD_THRESHOLD`` times in a row."""
        if not _LOOP_GUARD_ENABLED:
            return ""
        key = self._tool_call_key(name, args)
        failed = _tool_call_failed(raw_output)
        if not failed:
            self._tool_fail_streak.pop(key, None)  # success clears this call's streak
            return ""
        streak = self._tool_fail_streak.get(key, 0) + 1
        self._tool_fail_streak[key] = streak
        if streak < _LOOP_GUARD_THRESHOLD:
            return ""
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
        if not self._prm_enabled:
            return
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
            self._last_step_score = reward.promise
            self.ctx.blackboard.post(
                self.name, "prm",
                f"step={step_index} promise={reward.promise:.2f} "
                f"progress={reward.progress:+.2f} conf={reward.confidence:.2f}",
            )
        except Exception as e:  # pragma: no cover - PRM must never break the loop
            log.debug("PRM scoring skipped: %s", e)

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
        bb = self.ctx.blackboard
        bb.post(self.name, "plan", f"role={self.role} depth={self.depth} brief={self.brief}")

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
            from .compaction import compact_messages
            messages = compact_messages(messages)

            try:
                # Stop BEFORE spending another call when the cap is already
                # hit. record_tokens() only checks AFTER the response lands,
                # so a goal at 99% of budget would otherwise still fire one
                # more (potentially expensive) call.
                self.ctx.budget.check()
                resp = await self.ctx.llm.complete_async(
                    system=self.system,
                    messages=messages,
                    tools=self.tools.to_anthropic(),
                    budget=self.ctx.budget,
                    max_tokens=4096,
                    thinking_budget=self._thinking_budget(),
                    model=self.model,
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
                                verdict = await verify_final(
                                    self.brief, final, self.ctx.llm, self.ctx.budget,
                                    proposer_model=self.model,
                                )
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

            def _answer_pending_tool_uses(reason: str) -> None:
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
                    for tc in resp.tool_calls:
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
                for tc, output in zip(resp.tool_calls, outputs):
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
