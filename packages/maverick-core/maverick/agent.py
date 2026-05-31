"""Recursive async agent.

v0.1.4: appends ``persona.render_persona_prompt()`` to the system
prompt of every agent so users can give the swarm a name and voice
without patching the kernel.
"""
from __future__ import annotations

import os
import secrets as _secrets
import uuid
from dataclasses import dataclass
from typing import Optional

from . import killswitch
from ._envparse import env_int
from .budget import BudgetExceeded
from .llm import model_for_role
from .swarm import SwarmContext
from .tools import ToolRegistry, base_registry
from .tools.agent_bus_tool import recv_from_agent, send_to_agent
from .tools.spawn import spawn_subagent_tool, spawn_swarm_tool


WORKER_SYSTEM_TEMPLATE = """You are a specialist agent in Maverick, a long-horizon multi-agent swarm.

Your role: {role}
Your depth in the swarm: {depth} (root = 0, max = {max_depth})

You have a single sub-goal. Plan briefly, then act.

Tools you can call include:
  - File / shell / read / write for the sandbox.
  - `ask_user` to queue a question for the user (async). Use sparingly, batch.
  - `spawn_subagent` to delegate a focused sub-task to a child specialist.
  - `spawn_swarm` to fan out INDEPENDENT sub-tasks in PARALLEL.
  - `mcp_<server>__<tool>` for any external MCP servers wired into config.

Rules:
1. If your task naturally decomposes into 2+ independent parts and you have depth budget remaining, prefer `spawn_swarm` for speed.
2. If a sub-task needs its own context window or a different specialty, use `spawn_subagent`.
3. When done, respond in plain text starting with `FINAL:` followed by your answer. No tool call.
4. Be precise. Cite exact paths, commands, results, and findings from your children.
5. Budget is enforced globally; spend wisely. Stop spawning if results so far are sufficient."""


ORCHESTRATOR_SYSTEM_TEMPLATE = """You are the orchestrator of a Maverick swarm.

You own a top-level goal. You do not execute work yourself; you decompose, delegate, and verify.

Standard playbook:
1. Plan: think through the goal. Identify which sub-tasks are independent (parallelizable) vs. sequential.
2. Spawn: use `spawn_swarm` to fan out independent sub-tasks in parallel. Use `spawn_subagent` for sequential dependencies.
3. Synthesize: aggregate findings from your children into a coherent answer.
4. Verify: before finalizing, check that the answer satisfies the original goal.
5. If you are blocked on info only the user can give, use `ask_user` (batched).
6. End with `FINAL:` followed by your synthesized answer.

You have a maximum spawn depth of {max_depth}. Use it wisely.

Available roles for children: researcher, coder, writer, analyst, summarizer, revisor.

External MCP tools (if any) appear as `mcp_<server>__<tool>`."""


@dataclass
class AgentResult:
    final: Optional[str] = None
    blocked_on_user: bool = False
    error: Optional[str] = None
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
    final_patch: Optional[str] = None


class Agent:
    def __init__(
        self,
        ctx: SwarmContext,
        role: str,
        brief: str,
        model_override: Optional[str] = None,
        depth: int = 0,
        parent: Optional["Agent"] = None,
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

    def _build_tools(self) -> ToolRegistry:
        reg = base_registry(
            self.ctx.world,
            self.ctx.sandbox,
            mcp_clients=self.ctx.mcp_clients,
            goal_id=self.ctx.goal_id,
            channel=self.ctx.channel,
            user_id=self.ctx.user_id,
            budget=self.ctx.budget,
        )
        # Cross-agent bus tools, bound to this agent's id so send records
        # the right sender and recv drains the right inbox.
        reg.register(send_to_agent(self.name))
        reg.register(recv_from_agent(self.name))
        if self.depth < self.ctx.max_depth:
            reg.register(spawn_subagent_tool(self))
            reg.register(spawn_swarm_tool(self))
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
            from .coding_mode import CODER_CODING_MODE_TEMPLATE, from_env as _cm_from_env
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
            except (ImportError, FileNotFoundError, ValueError):
                pass

        return base

    def _thinking_budget(self) -> Optional[int]:
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
            ApplyResult, ApplySummary, SearchReplaceBlock, apply_blocks,
            parse_blocks, render_diff,
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
                try:
                    wt = _sub.run(
                        [
                            "git", "-C", str(workdir), "worktree", "add",
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
        from pathlib import Path as _Path
        import subprocess as _sub
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
        from .hooks import HookContext, HookEvent, dispatch as _dispatch_hooks
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
            except Exception:  # pragma: no cover -- shield must never block tools on its own bug
                pass
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
        # Council-of-20 security finding: a literal `</tool_output>` in
        # `output` (attacker-controlled file contents, shell stdout, MCP
        # response) escapes the framing and lets following text read as
        # authoritative LLM context. Use a random per-call nonce so the
        # close tag is unforgeable. `secrets.token_hex(8)` = 16 hex chars.
        nonce = _secrets.token_hex(8)
        return (
            f"<tool_output tool={name!r} id={nonce}>\n"
            f"{output}\n"
            f"</tool_output {nonce}>"
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
        stripped = (output or "").lstrip()
        tr: dict = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": output,
        }
        if stripped.startswith("ERROR") or stripped.startswith("BLOCKED by Shield"):
            tr["is_error"] = True
        return tr

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

        for step in range(self.max_steps):
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
                return AgentResult(error=str(e), role=self.role, name=self.name)

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
                return AgentResult(error=str(e), role=self.role, name=self.name)

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
                        patch, sr_summary = self._extract_and_apply_patch(final)
                        # Reset workdir AFTER capturing the diff so the
                        # verifier branch (and downstream evaluators) see
                        # HEAD when they re-apply.
                        if sr_summary is not None:
                            self._reset_workdir()
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
                                    patch, _ = self._extract_and_apply_patch(final)
                                    if patch is not None:
                                        # We applied to disk; reset for the
                                        # verifier's own apply.
                                        self._reset_workdir()
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

                                apply_ok = self._git_apply(patch)

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
                                        test_result = run_failing_tests(
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
                                        self._reset_workdir()

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

                        try:
                            from .verifier import verify_final
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
                                return AgentResult(
                                    final=final, role=self.role, name=self.name,
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
                    from .hooks import HookEvent, emit as _emit_hook
                    await _emit_hook(
                        HookEvent.STOP,
                        goal_id=self.ctx.goal_id, agent_role=self.role,
                        extra={"name": self.name, "final": final},
                    )
                    return AgentResult(
                        final=final, role=self.role, name=self.name,
                        verifier_confidence=verdict.confidence if verdict else 1.0,
                        verifier_critique=verdict.critique if verdict else "",
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
            if run_parallel:
                import asyncio as _asyncio
                # Account every call up front; record_tool_call mirrors
                # the serial path (one per tool, same count).
                for tc in resp.tool_calls:
                    self.ctx.budget.record_tool_call()
                outputs = await _asyncio.gather(
                    *(self._run_tool(tc.name, tc.input) for tc in resp.tool_calls)
                )
                # Preserve original call order in the results (matched by
                # tool_use_id, but ordering keeps traces readable).
                for tc, output in zip(resp.tool_calls, outputs):
                    bb.post(
                        self.name, "observation",
                        f"tool={tc.name} -> {output[:500]}",
                    )
                    tool_results.append(self._make_tool_result(tc.id, output))
            else:
                for tc in resp.tool_calls:
                    # Per-tool halt check: a serial turn may run a long
                    # shell command; honour a halt that lands mid-turn.
                    try:
                        killswitch.check()
                    except killswitch.Halted as e:
                        bb.post(self.name, "error", f"halted: {e}")
                        return AgentResult(
                            error=f"halted: {e}", role=self.role, name=self.name,
                        )
                    self.ctx.budget.record_tool_call()
                    output = await self._run_tool(tc.name, tc.input)
                    if tc.name == "ask_user":
                        blocked = True
                    bb.post(
                        self.name, "observation",
                        f"tool={tc.name} -> {output[:500]}",
                    )
                    tool_results.append(self._make_tool_result(tc.id, output))

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
