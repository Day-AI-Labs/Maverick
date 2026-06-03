"""code_exec: programmatic tool calling (the run-to-completion slice).

Anthropic's programmatic-tool-calling pattern, scoped to today's run-to-completion
sandbox (no interactive sessions yet): the model declares a set of tool calls plus
a Python script. The host runs the tool calls FIRST (through the agent's shielded
tool path), injects their outputs into the script as a ``tools`` dict, runs the
script in the sandbox, and returns ONLY the script's stdout. The raw tool outputs
-- and the data-flow between them -- stay in the sandbox, out of the model's
context, so the model can fetch/query many things and return just a filtered or
aggregated summary in a single turn.

What this slice does NOT do: dynamic mid-execution tool calls (the script cannot
issue NEW tool calls based on intermediate results). That needs interactive
sandbox sessions -- a separate effort. Here the tool calls are resolved up front.

Safety:
  - Declared tool calls go through ``agent._run_tool``, so the shield, PreToolUse
    / PostToolUse hooks, secret redaction, the per-result size cap, and the tool
    ACL all apply exactly as for a normal call; each is budget-accounted.
  - The script runs in the sandbox (CLAUDE.md rule #4) -- same isolation as the
    ``shell`` tool -- never in-process.
  - Opt-in: ``[capabilities] code_exec`` or ``MAVERICK_CODE_EXEC=1``.
"""
from __future__ import annotations

import asyncio
import json

from . import Tool, sandbox_run

# Bound the up-front fan-out; each declared call is budget-accounted besides.
_MAX_DECLARED_CALLS = 24
_CODE_TIMEOUT = 120.0


def code_exec_tool(agent) -> Tool:
    """Build the code_exec tool bound to ``agent`` (for its shielded _run_tool,
    sandbox, and budget)."""

    async def fn(args: dict) -> str:
        code = str(args.get("code") or "")
        if not code.strip():
            return "ERROR: `code` is required (a Python script to run)."
        declared = args.get("tool_calls") or []
        if not isinstance(declared, list):
            return "ERROR: `tool_calls` must be a list of {name, arguments}."
        if len(declared) > _MAX_DECLARED_CALLS:
            return (f"ERROR: too many tool_calls ({len(declared)}; max "
                    f"{_MAX_DECLARED_CALLS}). Batch fewer, or loop inside the script "
                    "over data a single call returns.")

        from ..agent import unframe_tool_output
        from ..budget import BudgetExceeded

        # 1. Run the declared tool calls FIRST, through the shielded path.
        tool_outputs: dict[str, str] = {}
        for i, call in enumerate(declared):
            if not isinstance(call, dict):
                return f"ERROR: tool_calls[{i}] must be an object with name + arguments."
            name = call.get("name")
            if not name:
                return f"ERROR: tool_calls[{i}] is missing 'name'."
            cargs = call.get("arguments")
            if cargs is None:
                cargs = call.get("input") or {}
            if not isinstance(cargs, dict):
                return f"ERROR: tool_calls[{i}].arguments must be an object."
            var = str(call.get("as") or f"{name}_{i}")
            try:
                agent.ctx.budget.record_tool_call()
            except BudgetExceeded as e:
                return f"ERROR: budget exhausted before running {name!r}: {e}"
            framed = await agent._run_tool(str(name), cargs)
            tool_outputs[var] = unframe_tool_output(framed)

        # 2. Build the script: the (already shielded + capped) outputs as a dict,
        # then the model's code. json.dumps of a str->str dict is valid Python.
        preamble = (
            "# Injected by code_exec: outputs of the tool_calls you declared,\n"
            "# keyed by your `as` (or '<name>_<index>'). Read them via tools[...].\n"
            "tools = " + json.dumps(tool_outputs) + "\n\n"
        )
        script = preamble + code

        # 3. Run the script in the sandbox (off the event loop). stdin carries
        # the script to `python3 -`; only its stdout returns to the model.
        try:
            rc, out, err = await asyncio.to_thread(
                sandbox_run, agent.ctx.sandbox, ["python3", "-"],
                timeout=_CODE_TIMEOUT, stdin=script,
            )
        except Exception as e:  # noqa: BLE001 -- surface as a tool error, don't crash the turn
            return f"ERROR: could not run the script: {type(e).__name__}: {e}"
        if rc != 0:
            return (
                f"ERROR: script exited {rc}.\n"
                f"--- stderr (tail) ---\n{(err or '').strip()[-2000:]}\n"
                f"--- stdout (tail) ---\n{(out or '').strip()[-2000:]}"
            )
        out = (out or "").strip()
        return out or "(script produced no stdout; print() the result you want returned)"

    return Tool(
        name="code_exec",
        description=(
            "Run a Python script in the sandbox to orchestrate work over tool "
            "outputs WITHOUT each raw output entering the conversation. Declare "
            "`tool_calls` (a list of {name, arguments[, as]}); they run first "
            "through the normal safety path and their outputs are injected into "
            "your script as a `tools` dict keyed by your `as` (or '<name>_<i>'). "
            "Your `code` filters/aggregates/computes over them and print()s the "
            "ONLY thing returned to you. Ideal for 'fetch/query N things, then "
            "summarize' so large intermediate data stays out of context. Note: "
            "the script can't issue NEW tool calls mid-run -- declare them up front."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python to run. Reads `tools[...]`; print() the result.",
                },
                "tool_calls": {
                    "type": "array",
                    "description": "Tool calls to run first; their outputs become `tools`.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "arguments": {"type": "object"},
                            "as": {
                                "type": "string",
                                "description": "Key for this result in `tools` (default '<name>_<i>').",
                            },
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": ["code"],
        },
        fn=fn,
    )


__all__ = ["code_exec_tool"]
