"""Recursive async agent.

Every node in the swarm is an `Agent`. Agents:
  - run an async tool-use loop against the LLM
  - may spawn sub-agents (single or parallel swarm) via tools
  - share blackboard, world model, budget, and sandbox via SwarmContext
  - have a depth (root=0) and a parent reference

The orchestrator is just an Agent with role='orchestrator' and a planning-
oriented system prompt. It uses spawn_swarm to fan out parallel workers.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from .budget import BudgetExceeded
from .llm import model_for_role
from .swarm import SwarmContext
from .tools import ToolRegistry, base_registry
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

Available roles for children: researcher, coder, writer, analyst, summarizer, revisor."""


@dataclass
class AgentResult:
    final: Optional[str] = None
    blocked_on_user: bool = False
    error: Optional[str] = None
    role: str = ""
    name: str = ""


class Agent:
    def __init__(
        self,
        ctx: SwarmContext,
        role: str,
        brief: str,
        depth: int = 0,
        parent: Optional["Agent"] = None,
        max_steps: int = 25,
    ):
        self.ctx = ctx
        self.role = role
        self.brief = brief
        self.depth = depth
        self.parent = parent
        self.max_steps = max_steps
        self.name = f"{role}-{depth}-{uuid.uuid4().hex[:6]}"

        self.tools = self._build_tools()
        self.system = self._build_system()
        self.model = model_for_role(role)

    def _build_tools(self) -> ToolRegistry:
        reg = base_registry(self.ctx.world, self.ctx.sandbox)
        # Only allow spawn if we have depth headroom.
        if self.depth < self.ctx.max_depth:
            reg.register(spawn_subagent_tool(self))
            reg.register(spawn_swarm_tool(self))
        return reg

    def _build_system(self) -> str:
        if self.role == "orchestrator":
            base = ORCHESTRATOR_SYSTEM_TEMPLATE.format(max_depth=self.ctx.max_depth)
        else:
            base = WORKER_SYSTEM_TEMPLATE.format(
                role=self.role, depth=self.depth, max_depth=self.ctx.max_depth
            )

        # Inject relevant skills from prior runs.
        if self.ctx.use_skills:
            try:
                from .skills import load_skills, relevant_skills, render_for_prompt

                skills = relevant_skills(self.brief, load_skills())
                if skills:
                    base = base + "\n\n" + render_for_prompt(skills)
            except Exception:
                pass

        return base

    def _thinking_budget(self) -> Optional[int]:
        # Orchestrator + revisor get extended thinking; workers don't (cost).
        if self.role in ("orchestrator", "revisor"):
            return 8000
        return None

    async def run(self) -> AgentResult:
        bb = self.ctx.blackboard
        bb.post(self.name, "plan", f"role={self.role} depth={self.depth} brief={self.brief}")

        messages: list[dict] = [
            {
                "role": "user",
                "content": (
                    f"Sub-goal: {self.brief}\n\n"
                    f"Recent swarm activity:\n{bb.render(40) or '(empty)'}\n\n"
                    "Plan briefly, then act. End with FINAL: <answer> when done."
                ),
            }
        ]

        for step in range(self.max_steps):
            try:
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

            # Record the assistant turn for proper conversation continuity.
            assistant_content: list[dict] = []
            if resp.thinking:
                # Note: thinking blocks must be preserved in subsequent turns.
                assistant_content.append({"type": "thinking", "thinking": resp.thinking})
            if resp.text:
                assistant_content.append({"type": "text", "text": resp.text})
            for tc in resp.tool_calls:
                assistant_content.append(
                    {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
                )
            messages.append({"role": "assistant", "content": assistant_content})

            if resp.text:
                if resp.text.startswith("FINAL:"):
                    final = resp.text[len("FINAL:") :].strip()
                    bb.post(self.name, "finding", final)
                    self.ctx.world.append_message(
                        self.ctx.goal_id, f"agent:{self.name}", final
                    )
                    return AgentResult(final=final, role=self.role, name=self.name)
                bb.post(self.name, "observation", resp.text[:1000])

            if not resp.tool_calls:
                if resp.text:
                    return AgentResult(final=resp.text, role=self.role, name=self.name)
                return AgentResult(
                    error="empty response with no tools", role=self.role, name=self.name
                )

            tool_results: list[dict] = []
            blocked = False
            for tc in resp.tool_calls:
                self.ctx.budget.record_tool_call()
                output = await self.tools.run(tc.name, tc.input)
                if tc.name == "ask_user":
                    blocked = True
                bb.post(
                    self.name,
                    "observation",
                    f"tool={tc.name} -> {output[:500]}",
                )
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": tc.id, "content": output}
                )

            messages.append({"role": "user", "content": tool_results})

            if blocked:
                return AgentResult(blocked_on_user=True, role=self.role, name=self.name)

        return AgentResult(
            error=f"hit max_steps={self.max_steps}",
            role=self.role,
            name=self.name,
        )
