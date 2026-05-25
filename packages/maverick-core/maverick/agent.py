"""Recursive async agent.

v0.1.4: appends ``persona.render_persona_prompt()`` to the system
prompt of every agent so users can give the swarm a name and voice
without patching the kernel.
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
        reg = base_registry(
            self.ctx.world,
            self.ctx.sandbox,
            mcp_clients=self.ctx.mcp_clients,
            goal_id=self.ctx.goal_id,
        )
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
        output = await self.tools.run(name, args)
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
        return (
            f"<tool_output tool={name!r}>\n"
            f"{output}\n"
            f"</tool_output>"
        )

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

            assistant_content: list[dict] = []
            if resp.thinking:
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
                output = await self._run_tool(tc.name, tc.input)
                if tc.name == "ask_user":
                    blocked = True
                bb.post(
                    self.name, "observation",
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
