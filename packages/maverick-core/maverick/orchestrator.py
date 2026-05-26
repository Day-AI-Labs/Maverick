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

    mcp_specs = load_mcp_specs_from_config()
    mcp_clients = await start_mcp_clients(mcp_specs) if mcp_specs else []

    try:
        ctx = SwarmContext(
            llm=llm, world=world, budget=budget, blackboard=blackboard,
            sandbox=sandbox, goal_id=goal_id, max_depth=max_depth,
            shield=shield, mcp_clients=mcp_clients,
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

        root = Agent(ctx=ctx, role="orchestrator", brief=brief, depth=0)

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
            _end_episode_with_spend(world, episode_id, result.error, "failure", budget)
            world.set_goal_status(goal_id, "blocked", result=result.error)
            return (
                f"Stopped: the assistant ran into an error and couldn't finish.\n"
                f"Detail: {result.error}\n"
                f"You can try again with: maverick resume #{goal_id}\n"
                f"[{budget.summary()}]"
            )

        summary = result.final or "(no answer)"
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

        try:
            skill = distill(goal.title, summary, blackboard, llm, budget=budget)
            skill_note = f"\n\n[distilled skill: {skill.name}]" if skill else ""
        except BudgetExceeded:
            skill_note = "\n\n[skill distill skipped: budget]"
        except Exception as e:
            skill_note = f"\n\n[skill distill error: {e}]"

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

    # Wave 10 (D9): per-attempt budget MUST stay below parent cap so
    # one expensive attempt cannot blow the harness-set dollar/wall
    # limits. The prior floors (1.50 / 1200s) made per-attempt > parent
    # for the typical harness Budget(max_dollars=3.0, max_wall_seconds=600).
    # We split the parent cap evenly across N, with a sensible floor only
    # for one-shot best-of-N=1 (which short-circuits to run_goal above).
    per_attempt_dollars = budget.max_dollars / n
    per_attempt_wall = budget.max_wall_seconds / n
    candidates: list[Candidate] = []

    for i in range(n):
        # Wave 9 fix (council M12): respect parent dollar cap.
        if budget.dollars >= budget.max_dollars * 0.95:
            log.info("best-of-N early break: parent budget 95%% spent")
            break

        from .budget import Budget as _Budget
        attempt_budget = _Budget(
            max_dollars=per_attempt_dollars,
            max_wall_seconds=per_attempt_wall,
            max_input_tokens=budget.max_input_tokens,
            max_output_tokens=budget.max_output_tokens,
            max_tool_calls=budget.max_tool_calls,
        )
        # Wave 9 fix (council H6): give each attempt a temperature nudge
        # so we get real diversity instead of 4× the same answer. The
        # nudge is wired via env so all providers/agents see it.
        prior_temp = os.environ.get("MAVERICK_TEMPERATURE")
        os.environ["MAVERICK_TEMPERATURE"] = str(round(0.2 + i * 0.25, 2))
        try:
            try:
                answer = await run_goal(
                    llm, world, attempt_budget, goal_id,
                    sandbox=sandbox, max_depth=max_depth,
                    conversation_id=conversation_id,
                )
            except Exception as e:
                log.warning("best-of-N attempt %d failed: %s", i, e)
                candidates.append(Candidate(
                    index=i, patch="", score=0.0,
                    apply_check_passed=False, error=str(e),
                ))
                # Roll the spend into the parent budget so we don't lie.
                budget.dollars += attempt_budget.dollars
                budget.input_tokens += attempt_budget.input_tokens
                budget.output_tokens += attempt_budget.output_tokens
                continue
        finally:
            # Restore temperature so the next call site isn't surprised.
            if prior_temp is None:
                os.environ.pop("MAVERICK_TEMPERATURE", None)
            else:
                os.environ["MAVERICK_TEMPERATURE"] = prior_temp

        budget.dollars += attempt_budget.dollars
        budget.input_tokens += attempt_budget.input_tokens
        budget.output_tokens += attempt_budget.output_tokens

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
