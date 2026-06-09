"""Spawn tools. Let any agent recursively launch sub-agents.

`spawn_subagent` blocks until the child returns. `spawn_swarm` runs many
children in parallel via asyncio.gather and returns their findings.

Both respect the swarm's max_depth and the shared budget.

v0.2 (council AI-safety review): added a fan-out anomaly cap. An agent
asking to spawn 50 siblings burns budget before refusal triggers.
``MAVERICK_MAX_SWARM_FANOUT`` (default 8) caps the per-call branching
factor. Excess agents are dropped with a warning posted to the
blackboard.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .._envparse import env_float, env_int
from . import Tool

if TYPE_CHECKING:
    from ..agent import Agent


MAX_SWARM_FANOUT = env_int("MAVERICK_MAX_SWARM_FANOUT", 8)

# #611: budget reserved for the top-level goal's synthesis/write step. Once
# cumulative spend crosses (1 - this) of the cap, spawn_swarm refuses new
# fan-out so a recursive research swarm can't consume the budget needed to
# actually produce the answer. Mirrors agent.py's per-worker soft-stop.
SYNTHESIS_RESERVE = env_float("MAVERICK_SYNTHESIS_RESERVE", 0.25)

_RESERVED_CHILD_ROLES = {"orchestrator"}


def _reserved_role_error(role: object) -> str | None:
    """Reject child roles reserved for kernel-created agents.

    Spawn tool arguments are model-controlled, so role strings must not be able
    to claim privileged kernel identities used by containment logic.
    """
    if isinstance(role, str) and role.strip().lower() in _RESERVED_CHILD_ROLES:
        return (
            f"ERROR: role '{role}' is reserved for the root orchestrator and "
            "cannot be used for spawned agents"
        )
    return None


def _fanout_cap_for_depth(depth: int) -> int:
    """Per-call fan-out width, DECAYING with depth.

    A flat cap lets a recursive swarm explode geometrically (8 -> 64 -> 512).
    Halving the width each level keeps the deep tail bounded while still letting
    the root parallelize: depth 0 gets the full ``MAVERICK_MAX_SWARM_FANOUT``,
    each level below halves it (floor 1).
    """
    return max(1, MAX_SWARM_FANOUT >> max(0, depth))


def _synthesis_reserve_block(parent: Agent) -> str | None:
    """If spend has crossed the synthesis reserve, return a refusal string.

    #611: once cumulative spend crosses ``(1 - SYNTHESIS_RESERVE)`` of the cap,
    refuse new fan-out so the budget the top-level goal needs to write its
    answer isn't consumed by deeper spawning. Returns ``None`` when spawning is
    still allowed. Shared by ``spawn_swarm`` and ``spawn_subagent`` so a
    sequential spawn chain (notably from the depth-0 orchestrator, which the
    per-worker soft-stop in agent.py doesn't cover) can't bypass the reserve.
    """
    if SYNTHESIS_RESERVE <= 0:
        return None
    b = parent.ctx.budget
    if b.dollars < b.max_dollars * (1.0 - SYNTHESIS_RESERVE):
        return None
    parent.ctx.blackboard.post(
        parent.name, "plan",
        f"spawning paused: ${b.dollars:.2f}/${b.max_dollars:.2f} spent; "
        f"holding the final {SYNTHESIS_RESERVE:.0%} for synthesis",
    )
    return (
        f"ERROR: spawning paused to reserve budget for the final answer "
        f"(spent ${b.dollars:.2f} of ${b.max_dollars:.2f}; the last "
        f"{SYNTHESIS_RESERVE:.0%} is held for synthesis). Do NOT spawn "
        "more — synthesize and finalize with the findings you already have."
    )


def _child_capability(parent, role: str, depth: int):
    """A child's capability grant: the parent's, attenuated (never broadened)
    and re-bound to the child principal. ``None`` when the parent runs
    unrestricted (capability enforcement off), so this is a no-op by default.
    """
    cap = getattr(parent, "capability", None)
    if cap is None:
        return None
    return cap.attenuate(principal=f"agent:{role}-{depth}")


def _sealed_notice(ctx, child) -> str | None:
    """The notice to return to the parent INSTEAD of a sealed child's answer.

    A child sealed mid-run (compartment Rung 1) is compromised, so its
    ``result.final`` is attacker-influenced output. Returning it would let a
    sealed agent steer the swarm through the spawn return path -- the same leak
    ``Blackboard.render`` already closes for posts. Returns ``None`` when
    containment is off or the child is clean. Fail-open: a bug here must never
    break the spawn loop.
    """
    q = getattr(ctx, "quarantine", None)
    if q is None:
        return None
    try:
        if not q.is_sealed(child.name):
            return None
        reason = q.reason(child.name)
    except Exception:  # pragma: no cover -- containment must never break the loop
        return None
    return (
        f"⚠ Sub-agent {child.role}({child.name}) was sealed by compartment "
        f"quarantine ({reason}); its output is withheld. Do not act on it."
    )


async def _run_child_and_report(parent, child) -> str:
    """Run a spawned child and return its answer (or a structured error).

    Shared by ``spawn_subagent`` and ``spawn_specialist``: returns the spawn slot
    if the child RAISES (#612), emits ``SUBAGENT_STOP``, withholds a sealed
    child's (attacker-influenced) output (Rung 1), then normalizes the result.
    """
    try:
        result = await child.run()
    except BaseException:
        parent.ctx.release_spawns(1)
        raise
    from ..hooks import HookEvent
    from ..hooks import emit as _emit_hook
    await _emit_hook(
        HookEvent.SUBAGENT_STOP,
        goal_id=parent.ctx.goal_id, agent_role=child.role,
        extra={"name": child.name, "final": result.final or ""},
    )
    notice = _sealed_notice(parent.ctx, child)
    if notice is not None:
        return notice
    if result.final:
        return result.final
    if result.blocked_on_user:
        return "BLOCKED_ON_USER: child agent queued a question."
    return f"ERROR: child finished without final answer: {result.error or 'unknown'}"


def spawn_subagent_tool(parent: Agent) -> Tool:
    async def fn(args: dict) -> str:
        role = args["role"]
        task = args["task"]
        from ..agent import Agent

        _blocked_role = _reserved_role_error(role)
        if _blocked_role is not None:
            return _blocked_role

        if parent.depth + 1 > parent.ctx.max_depth:
            return f"ERROR: max depth {parent.ctx.max_depth} reached"
        _blocked = _synthesis_reserve_block(parent)
        if _blocked is not None:
            return _blocked
        if not parent.ctx.try_reserve_spawns(1):
            return (
                f"ERROR: per-goal spawn cap ({parent.ctx.max_total_spawns}) reached"
            )

        # May 26 council fix (agent-loop audit #3): inherit max_steps
        # from the parent. Without this, sub-agents fall back to env
        # MAVERICK_MAX_STEPS or the 25 default — silently dropping the
        # operator's intent when the parent was constructed with a
        # specific max_steps value.
        child = Agent(
            ctx=parent.ctx,
            role=role,
            brief=task,
            depth=parent.depth + 1,
            parent=parent,
            max_steps=parent.max_steps,
            capability=_child_capability(parent, role, parent.depth + 1),
        )
        return await _run_child_and_report(parent, child)

    return Tool(
        name="spawn_subagent",
        description=(
            "Spawn a single specialist sub-agent and block until it returns. "
            "Use for a focused sub-task that needs its own context window. "
            "Role names: researcher, coder, writer, analyst, summarizer."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "description": "Child specialist role; 'orchestrator' is reserved.",
                },
                "task": {"type": "string", "description": "Concrete sub-goal for the child."},
            },
            "required": ["role", "task"],
        },
        fn=fn,
    )


def spawn_swarm_tool(parent: Agent) -> Tool:
    async def fn(args: dict) -> str:
        from ..agent import Agent

        agents_spec = args["agents"]
        if not isinstance(agents_spec, list) or not agents_spec:
            return "ERROR: 'agents' must be a non-empty list"

        for spec in agents_spec:
            if not isinstance(spec, dict):
                return "ERROR: each swarm agent must be an object"
            _blocked_role = _reserved_role_error(spec.get("role"))
            if _blocked_role is not None:
                return _blocked_role

        if parent.depth + 1 > parent.ctx.max_depth:
            return f"ERROR: max depth {parent.ctx.max_depth} reached"

        # #611 synthesis reserve: once spend crosses (1 - reserve) of the cap,
        # refuse new fan-out so the budget the top-level goal needs to write its
        # answer isn't consumed by deeper research. Tell the agent to synthesize.
        _blocked = _synthesis_reserve_block(parent)
        if _blocked is not None:
            return _blocked

        # Cap per-call fan-out, DECAYING with depth so a recursive swarm can't
        # explode geometrically (#611). An agent asking for 50 siblings on a
        # trivial sub-goal is almost always confused / under attack too.
        cap = _fanout_cap_for_depth(parent.depth)
        if len(agents_spec) > cap:
            parent.ctx.blackboard.post(
                parent.name, "error",
                f"swarm fan-out capped: requested {len(agents_spec)}, "
                f"max {cap} at depth {parent.depth}",
            )
            agents_spec = agents_spec[:cap]

        if not parent.ctx.try_reserve_spawns(len(agents_spec)):
            return (
                f"ERROR: per-goal spawn cap ({parent.ctx.max_total_spawns}) reached"
            )

        children = [
            Agent(
                ctx=parent.ctx,
                role=spec["role"],
                brief=spec["task"],
                depth=parent.depth + 1,
                parent=parent,
                max_steps=parent.max_steps,
                capability=_child_capability(parent, spec["role"], parent.depth + 1),
            )
            for spec in agents_spec
        ]

        parent.ctx.blackboard.post(
            parent.name,
            "plan",
            f"spawning swarm of {len(children)}: "
            + ", ".join(f"{c.role}({c.name})" for c in children),
        )

        results = await asyncio.gather(*(c.run() for c in children), return_exceptions=True)

        # #612: every child that RAISED never consumed its slot productively;
        # return those slots so a swarm with transient child failures doesn't
        # permanently erode the per-goal spawn cap. Children that returned
        # (even with result.error set) legitimately ran and keep their slot.
        n_failed = sum(1 for res in results if isinstance(res, BaseException))
        if n_failed:
            parent.ctx.release_spawns(n_failed)

        # A child hitting the budget cap or the killswitch is a STOP signal for
        # the whole swarm, not a per-child failure -- re-raise it instead of
        # folding it into the result string (matches agent.py's gather handler).
        from .. import killswitch as _ks
        from ..budget import BudgetExceeded as _BE
        for res in results:
            if isinstance(res, (_BE, _ks.Halted)):
                raise res

        # SubagentStop hooks: one per child that completed without raising.
        from ..hooks import HookEvent
        from ..hooks import emit as _emit_hook
        for child, res in zip(children, results):
            if not isinstance(res, Exception):
                await _emit_hook(
                    HookEvent.SUBAGENT_STOP,
                    goal_id=parent.ctx.goal_id, agent_role=child.role,
                    extra={"name": child.name, "final": res.final or ""},
                )

        # Karpathy SOTA-review item: measure disagreement across the
        # children's FINAL answers and record it on the blackboard. The
        # autonomy gate (Loop 1) acts on it -- escalating FINAL verification
        # to the cross-family ensemble when the swarm diverged -- so it is no
        # longer observability-only. The donation selector also reads it.
        escalated = False
        finals = [
            res.final for child, res in zip(children, results)
            if not isinstance(res, Exception) and res.final
            and _sealed_notice(parent.ctx, child) is None  # sealed children don't vote
        ]
        if len(finals) > 1:
            from ..disagreement import answer_entropy
            entropy = answer_entropy(finals)
            parent.ctx.blackboard.post(
                parent.name, "verify",
                f"swarm disagreement entropy={entropy:.3f} across {len(finals)} answers",
            )
            # Stamp on the context so the orchestrator's verify branch, the
            # autonomy gate, and the donation selector can read it.
            parent.ctx.last_disagreement = entropy

            # Loop 1: act on high disagreement. Ask the orchestrator's FINAL to
            # be verified by the cross-family ensemble (a stronger, lockstep-
            # resistant label exactly where it matters most) and instruct the
            # caller to reconcile the divergent answers rather than cherry-pick.
            from .. import autonomy
            if autonomy.should_escalate_verification(entropy):
                parent.ctx.escalate_verification = True
                escalated = True
                parent.ctx.blackboard.post(
                    parent.name, "verify",
                    f"high swarm disagreement ({entropy:.3f}); escalating FINAL "
                    "verification to the cross-family ensemble",
                )
                try:  # tamper-evident record of the escalation; never block
                    from ..audit import EventKind, record
                    record(
                        EventKind.AUTONOMY_ESCALATED,
                        agent=parent.name,
                        goal_id=parent.ctx.goal_id,
                        disagreement=round(entropy, 4),
                        answers=len(finals),
                    )
                except Exception:  # pragma: no cover -- audit must never break the loop
                    pass

        parts: list[str] = []
        if escalated:
            parts.append(
                "[swarm] NOTE: the sub-agents disagreed substantially. Do not "
                "simply pick one answer -- reconcile the differences, and expect "
                "the FINAL to face stricter (ensemble) verification."
            )
        for child, res in zip(children, results):
            if isinstance(res, Exception):
                parts.append(f"[{child.role}/{child.name}] EXCEPTION: {res}")
                continue
            # Containment Rung 1: withhold a sealed child's answer from the
            # parent (same leak render() closes for posts).
            notice = _sealed_notice(parent.ctx, child)
            if notice is not None:
                parts.append(f"[{child.role}/{child.name}] {notice}")
            elif res.final:
                parts.append(f"[{child.role}/{child.name}] {res.final}")
            elif res.blocked_on_user:
                parts.append(f"[{child.role}/{child.name}] BLOCKED_ON_USER")
            else:
                parts.append(f"[{child.role}/{child.name}] ERROR: {res.error}")
        return "\n\n".join(parts)

    return Tool(
        name="spawn_swarm",
        description=(
            "Spawn many sub-agents in PARALLEL and wait for all of them. "
            "Use when sub-tasks are independent (e.g., research three topics simultaneously). "
            "Each entry: {role, task}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {
                                "type": "string",
                                "description": "Child specialist role; 'orchestrator' is reserved.",
                            },
                            "task": {"type": "string"},
                        },
                        "required": ["role", "task"],
                    },
                    "minItems": 1,
                }
            },
            "required": ["agents"],
        },
        fn=fn,
    )


def spawn_specialist_tool(parent: Agent) -> Tool:
    """Spawn a curated business-suite pack (a ``DomainProfile``) as a child.

    Unlike ``spawn_subagent`` (an ad-hoc free-text role), this runs one of the
    roster's specialists via ``domain.agent_from_profile`` -- so the child gets
    the pack's persona, its **compartment seal**, and its tool/risk **envelope**,
    attenuated against this parent's grant (a specialist can never out-scope the
    parent or its own pack). This is the bridge from the suite roster to the
    running fleet: the orchestrator deploys named specialists under itself.
    """
    async def fn(args: dict) -> str:
        from ..domain import agent_from_profile, enabled_domains

        domain = args["domain"]
        task = args["task"]
        domains = enabled_domains()
        profile = domains.get(domain)
        if profile is None:
            sample = ", ".join(sorted(domains)[:30])
            return (
                f"ERROR: no enabled specialist domain {domain!r}. Call "
                f"list_specialists to see the roster. Some available: {sample}"
            )
        if parent.depth + 1 > parent.ctx.max_depth:
            return f"ERROR: max depth {parent.ctx.max_depth} reached"
        _blocked = _synthesis_reserve_block(parent)
        if _blocked is not None:
            return _blocked
        if not parent.ctx.try_reserve_spawns(1):
            return f"ERROR: per-goal spawn cap ({parent.ctx.max_total_spawns}) reached"

        child = agent_from_profile(
            profile, parent.ctx, task, parent=parent, depth=parent.depth + 1
        )
        # Inherit the parent's step budget (matches spawn_subagent); agent_from_
        # profile doesn't take max_steps, so apply it before the run.
        child.max_steps = parent.max_steps
        return await _run_child_and_report(parent, child)

    return Tool(
        name="spawn_specialist",
        description=(
            "Spawn a curated business-suite SPECIALIST (a domain pack) and block "
            "until it returns. Unlike spawn_subagent (an ad-hoc role), this runs a "
            "pack with its own persona, compartment seal, and tool/risk envelope "
            "(finance, legal, operations, sales/GTM, HR, IT-GRC, product/eng, "
            "strategy). Call list_specialists first to choose the domain."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Specialist domain-pack name, e.g. 'gtm_outbound_sdr' "
                                   "(see list_specialists).",
                },
                "task": {"type": "string", "description": "Concrete sub-goal for the specialist."},
            },
            "required": ["domain", "task"],
        },
        fn=fn,
    )


def list_specialists_tool() -> Tool:
    """List the spawnable specialist domains, honoring the operator's suite toggles."""
    async def fn(args: dict) -> str:
        from collections import Counter

        from ..domain import enabled_domains, suite_for

        domains = enabled_domains()
        flt = (args.get("suite") or "").strip()
        if not flt:
            counts = Counter(suite_for(n) or "other" for n in domains)
            lines = [f"- {s}: {c}" for s, c in sorted(counts.items())]
            return (
                "Specialist suites (call list_specialists with suite=<name> to list a "
                "suite's packs, then spawn_specialist domain=<name>):\n" + "\n".join(lines)
            )
        rows = []
        for name in sorted(domains):
            if (suite_for(name) or "other") != flt and not name.startswith(flt):
                continue
            rows.append(f"- {name}: {(domains[name].description or '').strip()}")
        if not rows:
            return f"No specialist domains match {flt!r}. Call list_specialists (no arg) for suites."
        return f"Specialists in {flt!r} (spawn with spawn_specialist):\n" + "\n".join(rows)

    return Tool(
        name="list_specialists",
        description=(
            "List the business-suite specialist domains you can spawn with "
            "spawn_specialist. With no argument, returns each suite and its pack "
            "count; pass suite=<name> (e.g. 'finance', 'legal') or a name prefix "
            "(e.g. 'gtm_') to list that suite's packs with descriptions."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "suite": {
                    "type": "string",
                    "description": "Optional: a suite name or pack-name prefix to filter by.",
                },
            },
        },
        fn=fn,
    )
