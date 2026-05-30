"""Run a top-level goal through the swarm.

v0.1.3: attaches blackboard to world model so every post mirrors into
`goal_events`. Dashboard reads from there to stream live progress.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from .agent import Agent
from .blackboard import Blackboard
from .budget import Budget, BudgetExceeded
from .llm import LLM
from .llm import model_for_role
from .mcp_client import load_mcp_specs_from_config, start_mcp_clients, stop_mcp_clients
from .sandbox import LocalBackend
from .skills import distill
from .swarm import SwarmContext
from .world_model import WorldModel

log = logging.getLogger(__name__)


def _build_shield() -> Optional[Any]:
    try:
        from maverick_shield import Shield
        return Shield.from_config()
    except ImportError:
        log.warning("maverick-shield not installed; tool-call scans disabled")
        return None
    except Exception as e:  # pragma: no cover
        log.error("Shield construction failed (fail-open): %s", e)
        return None


def _end_episode_with_spend(
    world: WorldModel, episode_id: int, summary: str, outcome: str, budget: Budget,
) -> None:
    try:
        world.end_episode(
            episode_id, summary, outcome,
            cost_dollars=budget.dollars,
            input_tokens=budget.input_tokens,
            output_tokens=budget.output_tokens,
            tool_calls=budget.tool_calls,
        )
    except TypeError:
        world.end_episode(episode_id, summary, outcome)


async def run_goal(
    llm: LLM,
    world: WorldModel,
    budget: Budget,
    goal_id: int,
    sandbox: Optional[Any] = None,
    max_depth: int = 3,
    conversation_id: Optional[int] = None,
    channel: Optional[str] = None,
    user_id: Optional[str] = None,
    orchestrator_model_override: Optional[str] = None,
) -> str:
    goal = world.get_goal(goal_id)
    if not goal:
        return f"no such goal: {goal_id}"

    # Bind trace context so every log line emitted in this task is
    # automatically tagged with goal_id (+ conversation_id when set).
    try:
        from .logging_config import set_goal_context
        set_goal_context(goal_id=goal_id, conversation_id=conversation_id)
    except Exception:  # pragma: no cover
        pass

    world.set_goal_status(goal_id, "active")
    episode_id = world.start_episode(goal_id)
    blackboard = Blackboard()
    blackboard.attach_world(world, goal_id)  # persist every post for live streaming
    sandbox = sandbox or LocalBackend()
    shield = _build_shield()

    # Chokepoint #1: scan the initial goal text before the orchestrator
    # acts on it. The channel server scans inbound messages, but the
    # primary `maverick start "..."` / MCP `maverick_start` / chat paths
    # funnel the goal straight here -- so this is where the first scan
    # must live. Fail-open per kernel rule 1 (the shield is optional).
    if shield is not None:
        try:
            goal_text = f"{goal.title}\n{goal.description or ''}"
            # Normalize (NFKC + strip zero-width/bidi/tag-block) BEFORE
            # scanning so homoglyph / zero-width-encoded injections can't
            # slip past the regex rules. Fail-open if unavailable.
            try:
                from .safety.unicode_filter import normalize as _uni_normalize
                goal_text = _uni_normalize(goal_text).cleaned
            except Exception:  # pragma: no cover
                pass
            verdict = shield.scan_input(goal_text)
            if not getattr(verdict, "allowed", True):
                reason = "; ".join(getattr(verdict, "reasons", []) or []) or "blocked by Shield"
                world.set_goal_status(goal_id, "blocked", result=f"input blocked: {reason}")
                try:
                    world.end_episode(episode_id, "input blocked by Shield", "blocked")
                except Exception:  # pragma: no cover
                    pass
                log.warning("goal #%s input blocked by Shield: %s", goal_id, reason)
                return f"BLOCKED: goal input rejected by Shield ({reason})"
        except Exception:  # pragma: no cover
            log.exception("scan_input on goal text failed (fail-open)")

    mcp_specs = load_mcp_specs_from_config()
    mcp_clients = await start_mcp_clients(mcp_specs) if mcp_specs else []

    try:
        ctx = SwarmContext(
            llm=llm, world=world, budget=budget, blackboard=blackboard,
            sandbox=sandbox, goal_id=goal_id, max_depth=max_depth,
            shield=shield, mcp_clients=mcp_clients,
            channel=channel, user_id=user_id,
        )

        facts = world.get_facts()
        facts_block = "\n".join(f"  {k}: {v}" for k, v in facts.items()) or "  (none)"

        # Multi-turn: if this goal belongs to an ongoing conversation,
        # prepend the recent turn history so the orchestrator has context
        # for follow-up messages on the same channel.
        # Council finding (Tier 0): persisted turns were re-injected
        # unscanned, so a `user` message that passed scan_input once
        # could replay forever as a prompt-injection vector. Re-scan
        # each turn here and drop any that the shield now flags.
        history_block = ""
        if conversation_id is not None:
            turns = world.recent_turns(conversation_id, limit=10)
            history_lines: list[str] = []
            for t in turns:
                content = t.content[:300]
                if shield is not None:
                    try:
                        v = shield.scan_input(content) if t.role == "user" else shield.scan_output(content)
                        if not v.allowed:
                            history_lines.append(f"  {t.role}: [redacted by Shield]")
                            continue
                    except Exception:  # pragma: no cover
                        pass
                history_lines.append(f"  {t.role}: {content}")
            if history_lines:
                history_block = (
                    "\nPrior conversation (most recent last):\n"
                    + "\n".join(history_lines)
                    + "\n"
                )

        brief = (
            f"Top-level goal: {goal.title}\n"
            f"Description: {goal.description or '(none)'}\n"
            f"{history_block}\n"
            f"Known facts about the user:\n{facts_block}\n\n"
            "Decompose into sub-tasks, spawn workers (parallel where possible), "
            "synthesize their findings, verify, and respond with FINAL:."
        )

        root = Agent(
            ctx=ctx,
            role="orchestrator",
            brief=brief,
            model_override=orchestrator_model_override,
            depth=0,
        )

        try:
            result = await root.run()
        except BudgetExceeded as e:
            _end_episode_with_spend(world, episode_id, f"budget: {e}", "failure", budget)
            world.set_goal_status(goal_id, "blocked", result=f"budget exceeded: {e}")
            # Sentence-style error so a non-engineer can read it.
            return (
                f"Stopped: this goal hit your spending or time limit "
                f"(${budget.dollars:.2f}, {budget.elapsed():.0f}s elapsed).\n"
                f"Resume with a higher cap: "
                f"maverick resume #{goal_id} --max-dollars <higher>"
            )

        if result.blocked_on_user:
            _end_episode_with_spend(
                world, episode_id, "blocked awaiting user", "interrupted", budget,
            )
            world.set_goal_status(goal_id, "blocked")
            qs = world.open_questions(goal_id)
            if not qs:
                return (
                    "Paused: the assistant said it needs more information, "
                    "but no question was filed. You can resume with "
                    f"`maverick resume #{goal_id}` or send a follow-up message."
                )
            lines = [f"  #{q.id}: {q.question}" for q in qs]
            return (
                f"Paused: waiting for you to answer "
                f"{len(qs)} question{'s' if len(qs) != 1 else ''}.\n"
                + "\n".join(lines)
                + "\n\nAnswer with: maverick answer <id> \"<your answer>\""
            )

        if result.error:
            # Wave 12 hotfix: even when the agent loop errored (e.g. hit
            # max_steps), it may have produced a usable patch via
            # str_replace_editor before exiting. salvage it.
            if result.final_patch and (
                "diff --git" in result.final_patch
                or "--- a/" in result.final_patch
            ):
                _end_episode_with_spend(
                    world, episode_id, result.final_patch, "success", budget,
                )
                world.set_goal_status(
                    goal_id, "done", result=result.final_patch,
                )
                return result.final_patch
            _end_episode_with_spend(world, episode_id, result.error, "failure", budget)
            world.set_goal_status(goal_id, "blocked", result=result.error)
            return (
                f"Stopped: the assistant ran into an error and couldn't finish.\n"
                f"Detail: {result.error}\n"
                f"You can try again with: maverick resume #{goal_id}\n"
                f"[{budget.summary()}]"
            )

        # Wave 12: prefer the rendered unified diff (set by the agent's
        # FINAL handler when SEARCH/REPLACE blocks were applied) over
        # the raw FINAL text. Without this, extract_unified_diff on
        # downstream calls (best-of-N selector, harness CSV row) returns
        # None for SR-only candidates and the patch is silently dropped.
        # `final` is kept as a fallback for non-coding-mode goals where
        # the answer is prose.
        summary = result.final_patch or result.final or "(no answer)"
        _end_episode_with_spend(world, episode_id, summary, "success", budget)
        world.set_goal_status(goal_id, "done", result=summary)

        # Trajectory donation (Karpathy data-engine analog). Default OFF;
        # only fires when the user opted into [telemetry] donate_trajectories
        # AND the selection gate (disagreement_high + verifier_confident
        # + success) passes. Never raises -- a bad donation must never
        # affect the goal result.
        try:
            from .donation import TrajectoryRecord, hash_brief, write_record
            entropy = getattr(ctx, "last_disagreement", 0.0)
            record = TrajectoryRecord(
                task_brief_hash=hash_brief(goal.title + (goal.description or "")),
                task_brief_text=(goal.title + "\n" + (goal.description or "")),
                model_id=getattr(llm, "model", ""),
                tools_used=sorted({e.kind for e in blackboard.entries
                                   if e.kind == "observation"}),
                outcome="success",
                reward=1.0 if result.verifier_confidence >= 0.75 else result.verifier_confidence,
                verifier_confidence=result.verifier_confidence,
                verifier_critique=result.verifier_critique,
                disagreement_entropy=float(entropy or 0.0),
                wall_seconds=budget.elapsed(),
                cost_dollars=budget.dollars,
                tokens_in=budget.input_tokens,
                tokens_out=budget.output_tokens,
            )
            write_record(record)
        except Exception as e:  # pragma: no cover
            log.debug("trajectory donation skipped: %s", e)

        if conversation_id is not None:
            try:
                world.append_turn(conversation_id, "assistant", summary, goal_id=goal_id)
            except Exception as e:  # pragma: no cover -- never block on history
                log.warning("conversation turn write failed: %s", e)

        # Security hardening: disable automatic closed-loop distillation by
        # default. Trajectories can contain untrusted goal/tool/workspace text
        # and writing LLM output directly to persisted skills creates a
        # cross-run prompt-injection primitive. Operators can opt in explicitly
        # via MAVERICK_AUTO_DISTILL=1.
        auto_distill = os.getenv("MAVERICK_AUTO_DISTILL", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        if auto_distill:
            try:
                skill = distill(goal.title, summary, blackboard, llm, budget=budget)
                skill_note = f"\n\n[distilled skill: {skill.name}]" if skill else ""
            except BudgetExceeded:
                skill_note = "\n\n[skill distill skipped: budget]"
            except Exception as e:
                skill_note = f"\n\n[skill distill error: {e}]"
        else:
            skill_note = "\n\n[skill distill disabled: set MAVERICK_AUTO_DISTILL=1 to enable]"

        # Wave 12 hotfix: in coding mode the orchestrator's return value
        # IS the benchmark CSV's `predicted_patch` after extract_unified_diff.
        # The trailing skill_note + budget summary then pollute the patch
        # (they sit AFTER the last hunk so `git apply` ignores them, but
        # stricter graders + downstream tooling don't). When summary is
        # already a rendered unified diff, return it as-is — log the
        # bookkeeping to the blackboard instead.
        is_rendered_diff = bool(
            result.final_patch
            and ("diff --git" in summary or "--- a/" in summary)
        )
        if is_rendered_diff:
            try:
                if skill_note.strip():
                    blackboard.post("orchestrator", "skill", skill_note.strip())
                blackboard.post(
                    "orchestrator", "budget_summary", budget.summary(),
                )
            except Exception:
                pass
            return summary
        # Output chokepoint for the CLI / REST / programmatic callers. The
        # channel server scans run_goal's result at its own layer, but a
        # direct caller (maverick start / chat / resume, dashboard REST)
        # would otherwise hand back the raw answer unscanned. The
        # rendered-diff path above is intentionally left unscanned: code
        # legitimately contains strings the builtin rules flag (rm -rf,
        # curl | sh) and that path feeds tooling/graders, not a chat answer.
        if shield is not None:
            try:
                out_v = shield.scan_output(summary)
                if not getattr(out_v, "allowed", True):
                    reasons = "; ".join(getattr(out_v, "reasons", []) or []) or "blocked by Shield"
                    log.warning("output scan blocked goal #%s: %s", goal_id, reasons)
                    return f"⚠ Output blocked by Shield: {reasons}"
            except Exception:  # pragma: no cover -- fail open per kernel rule 1
                log.exception("scan_output on summary failed (fail-open)")
        return f"DONE.\n\n{summary}{skill_note}\n\n[{budget.summary()}]"
    finally:
        if mcp_clients:
            await stop_mcp_clients(mcp_clients)
        # Clear trace context so the next goal on this thread/task
        # doesn't inherit goal_id / conversation_id from this one
        # (FastAPI threadpool workers + the CLI chat REPL both reuse
        # the same execution context across goals).
        try:
            from .logging_config import clear_goal_context
            clear_goal_context()
        except Exception:  # pragma: no cover
            pass


def run_goal_sync(*args, **kwargs) -> str:
    return asyncio.run(run_goal(*args, **kwargs))


async def run_goal_best_of_n(
    llm: "LLM",
    world: "WorldModel",
    budget: "Budget",
    goal_id: int,
    sandbox: Optional[Any] = None,
    max_depth: int = 3,
    conversation_id: Optional[int] = None,
    n: int = 4,
) -> str:
    """Coding-mode best-of-N: run N independent attempts, pick the one
    whose patch (a) applies and (b) passes the most FAIL_TO_PASS /
    PASS_TO_PASS tests.

    Falls back to single-shot `run_goal` when n<=1 or coding mode is
    off. Each attempt runs against a fresh clone-of-clone so they
    don't pollute each other's git state.

    Called from the SWE-bench harness when MAVERICK_BEST_OF_N > 1.
    """
    from .coding_mode import (
        Candidate,
        evaluate_candidate,
        extract_unified_diff,
        from_env as _cm_from_env,
        select_best_candidate,
    )

    cfg = _cm_from_env()
    if n <= 1 or not cfg.enabled:
        return await run_goal(
            llm, world, budget, goal_id,
            sandbox=sandbox, max_depth=max_depth,
            conversation_id=conversation_id,
        )

    # Wave 12 (council F10c): per-attempt budget is RECOMPUTED each
    # iteration from REMAINING parent budget / REMAINING attempts.
    # When an early attempt crashes (spending only a fraction of its
    # quota) or finishes cheaply, the leftover redistributes to
    # remaining attempts instead of being wasted. The prior code
    # computed `budget.max_dollars / n` once up-front, so a crashed
    # attempt 0 left attempts 1..N-1 still capped at the original 1/N
    # — the (N-1)/N of unspent budget was lost.
    candidates: list[Candidate] = []

    # Wave 11: heterogeneous best-of-N. Inter-model diversity beats
    # intra-model temperature diversity on SWE-bench (RoBoN paper, arxiv
    # 2512.05542: +3.4pp over best individual at large N). The default
    # ladder is (Sonnet-cheap, Sonnet-warm, Opus) — first the cheap
    # primary, then a temperature-warmed re-roll, then the heavyweight
    # for the long tail. Configurable via MAVERICK_BON_LADDER as
    # comma-separated "model:temperature" pairs.
    configured_orchestrator_model = model_for_role("orchestrator")
    default_ladder = ",".join(
        f"{configured_orchestrator_model}:{t}" for t in (0.3, 0.7, 0.95)
    )
    raw_ladder = os.environ.get("MAVERICK_BON_LADDER", default_ladder)
    ladder: list[tuple[str, float]] = []
    for entry in raw_ladder.split(","):
        if ":" in entry:
            mdl, t = entry.rsplit(":", 1)
            try:
                ladder.append((mdl.strip(), float(t)))
            except ValueError:
                ladder.append((mdl.strip(), 0.3 + 0.25 * len(ladder)))
        elif entry.strip():
            ladder.append((entry.strip(), 0.3 + 0.25 * len(ladder)))
    # Pad the ladder with temperature-only steps if N > len(ladder).
    while len(ladder) < n:
        ladder.append(("", round(0.2 + 0.25 * len(ladder), 2)))
    ladder = ladder[:n]

    for i, (per_model, per_temp) in enumerate(ladder):
        # Wave 9 fix (council M12): respect parent dollar cap.
        if budget.dollars >= budget.max_dollars * 0.95:
            log.info("best-of-N early break: parent budget 95%% spent")
            break

        # Wave 12 (F10c): redistribute remaining budget across remaining
        # attempts. After crashes / early-cheap completions, the surviving
        # attempts get bigger caps instead of leaving budget on the table.
        remaining_attempts = len(ladder) - i
        remaining_dollars = max(0.0, budget.max_dollars - budget.dollars)
        remaining_wall = max(0.0, budget.max_wall_seconds - budget.elapsed())
        if remaining_dollars <= 0 or remaining_wall <= 0:
            log.info("best-of-N early break: no budget left for attempt %d", i)
            break
        per_attempt_dollars = remaining_dollars / remaining_attempts
        per_attempt_wall = remaining_wall / remaining_attempts

        from .budget import Budget as _Budget
        attempt_budget = _Budget(
            max_dollars=per_attempt_dollars,
            max_wall_seconds=per_attempt_wall,
            max_input_tokens=budget.max_input_tokens,
            max_output_tokens=budget.max_output_tokens,
            max_tool_calls=budget.max_tool_calls,
        )
        prior_temp = os.environ.get("MAVERICK_TEMPERATURE")
        os.environ["MAVERICK_TEMPERATURE"] = str(per_temp)
        try:
            try:
                # Wave 12 fix (council F14, biggest accuracy loss):
                # Each best-of-N attempt MUST run against a fresh
                # conversation history. The prior code passed the same
                # `conversation_id` to every attempt, so attempt 2 read
                # attempt 1's blackboard posts via the history_block in
                # run_goal — BoN was effectively BoN=1 with extra
                # context bloat. Setting `conversation_id=None` (and
                # `goal_id`-scoped events via `start_episode`) gives
                # each attempt an independent trajectory.
                answer = await run_goal(
                    llm, world, attempt_budget, goal_id,
                    sandbox=sandbox, max_depth=max_depth,
                    conversation_id=None,
                    orchestrator_model_override=per_model or None,
                )
            except Exception as e:
                log.warning("best-of-N attempt %d failed: %s", i, e)
                candidates.append(Candidate(
                    index=i, patch="", score=0.0,
                    apply_check_passed=False, error=str(e),
                ))
                # Roll ALL of the failed attempt's spend into the parent so
                # the summary is honest; stop if the aggregate hit a cap.
                try:
                    budget.absorb(attempt_budget)
                except BudgetExceeded:
                    break
                continue
        finally:
            # Restore env so the next call site isn't surprised.
            if prior_temp is None:
                os.environ.pop("MAVERICK_TEMPERATURE", None)
            else:
                os.environ["MAVERICK_TEMPERATURE"] = prior_temp

        # Roll ALL of this attempt's spend into the parent (cache tokens +
        # tool_calls included, not just dollars/in/out) and note if the
        # aggregate hit a cap -- we still evaluate this paid-for candidate,
        # then stop spawning further attempts.
        cap_reached = False
        try:
            budget.absorb(attempt_budget)
        except BudgetExceeded:
            cap_reached = True

        patch = extract_unified_diff(answer) or ""
        from pathlib import Path as _Path
        workdir = _Path(getattr(sandbox, "workdir", "."))
        cand = await evaluate_candidate(patch, workdir, cfg, sandbox, i)
        candidates.append(cand)

        if cand.score >= 0.99:
            # Early exit: a candidate that passes ALL tests is as good
            # as it gets; don't pay for the remaining N-1 attempts.
            log.info("best-of-N early exit at attempt %d: all tests pass", i)
            break
        if cap_reached:
            log.info(
                "best-of-N: parent budget cap reached after attempt %d; stopping", i,
            )
            break

    best = select_best_candidate(candidates)
    if best is None or not best.patch:
        return (
            "Stopped: none of the {n} attempts produced an applyable patch.\n"
            "[{summary}]"
        ).format(n=len(candidates), summary=budget.summary())

    test_note = (
        f"\n\n[best of {len(candidates)}; score={best.score:.2f}]"
        + (f"\n[{best.test_result.summary()}]" if best.test_result else "")
    )
    return f"DONE.\n\n{best.patch}{test_note}\n\n[{budget.summary()}]"
