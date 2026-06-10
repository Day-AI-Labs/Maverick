"""AutoGen + CrewAI interop (roadmap: 2027 H2 ecosystem).

The LangChain adapter's two directions, extended to the other two frameworks
people actually run multi-agent stacks on. The delegation core is shared —
:func:`maverick.langchain_adapter.run_maverick_goal` (transport-agnostic,
already unit-tested) — so this module is wrappers only:

  - **Maverick as an AutoGen tool** — :func:`maverick_autogen_tool` returns a
    plain typed function (AutoGen 0.4 ``FunctionTool``-compatible; AutoGen
    registers ordinary callables with docstrings), optionally wrapped in
    ``autogen_core.tools.FunctionTool`` when the package is installed.
  - **Maverick as a CrewAI tool** — :func:`maverick_crewai_tool` returns a
    CrewAI ``BaseTool`` subclass instance (lazy import, clear install hint).
  - **Their tools as Maverick tools** — :func:`wrap_autogen_tool` /
    :func:`wrap_crewai_tool` adapt an AutoGen ``FunctionTool`` / CrewAI
    ``BaseTool`` into a Maverick :class:`~maverick.tools.Tool`, so the swarm
    can call into either ecosystem's tools.

Nothing here imports ``autogen``/``crewai`` at module import time; each
wrapper lazy-imports and raises an actionable hint when the package is
absent (mirrors the ``[langchain]`` extra discipline).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from .langchain_adapter import run_maverick_goal
from .tools import Tool

_GOAL_DESCRIPTION = (
    "Delegate a goal to the Maverick agent swarm (planning, tools, "
    "verification) and return its result text. Use for multi-step work "
    "that needs real tools rather than a single completion."
)


# ---- Maverick as an AutoGen tool -------------------------------------------

def maverick_autogen_callable(*, max_dollars: float = 2.0, **binds: Any):
    """The plain typed callable AutoGen registers as a tool.

    AutoGen (0.4's ``FunctionTool``, and 0.2's ``register_function``) wraps
    ordinary Python callables whose signature + docstring become the schema —
    so the core adapter is dependency-free and the FunctionTool wrapper below
    is optional sugar."""
    def run_maverick(goal: str, description: str = "") -> str:
        """Delegate a goal to the Maverick agent swarm and return its result."""
        return run_maverick_goal(goal, description, max_dollars=max_dollars, **binds)

    return run_maverick


def maverick_autogen_tool(*, max_dollars: float = 2.0, **binds: Any):
    """Maverick as an AutoGen ``FunctionTool`` (needs ``autogen-core``)."""
    try:
        from autogen_core.tools import FunctionTool
    except ImportError as e:
        raise ImportError(
            "autogen-core not installed. Run: pip install autogen-core "
            "(or use maverick_autogen_callable(), which has no dependency)"
        ) from e
    return FunctionTool(
        maverick_autogen_callable(max_dollars=max_dollars, **binds),
        description=_GOAL_DESCRIPTION,
        name="run_maverick",
    )


# ---- Maverick as a CrewAI tool ----------------------------------------------

def maverick_crewai_tool(*, max_dollars: float = 2.0, **binds: Any):
    """Maverick as a CrewAI tool (needs ``crewai``).

    Returns an instance of a ``crewai.tools.BaseTool`` subclass whose ``_run``
    delegates to the swarm."""
    try:
        from crewai.tools import BaseTool  # type: ignore[import-not-found]
    except ImportError as e:
        raise ImportError(
            "crewai not installed. Run: pip install crewai"
        ) from e

    class MaverickTool(BaseTool):  # type: ignore[misc,valid-type]
        name: str = "run_maverick"
        description: str = _GOAL_DESCRIPTION

        def _run(self, goal: str, description: str = "") -> str:
            return run_maverick_goal(goal, description,
                                     max_dollars=max_dollars, **binds)

    return MaverickTool()


# ---- Their tools as Maverick tools ------------------------------------------

def _schema_or_default(obj: Any) -> dict:
    """Best-effort JSON schema from a framework tool's args model."""
    model = getattr(obj, "args_type", None)
    if callable(model):
        try:
            model = model()
        except Exception:
            model = None
    if model is None:
        model = getattr(obj, "args_schema", None)
    schema = None
    if model is not None:
        dump = getattr(model, "model_json_schema", None)
        if callable(dump):
            try:
                schema = dump()
            except Exception:
                schema = None
    if isinstance(schema, dict) and schema.get("type") == "object":
        return schema
    return {"type": "object", "properties": {"input": {"type": "string"}},
            "required": ["input"]}


def _result_text(out: Any) -> str:
    if isinstance(out, str):
        return out
    try:
        return json.dumps(out, default=str)
    except (TypeError, ValueError):
        return str(out)


def wrap_autogen_tool(autogen_tool: Any) -> Tool:
    """Adapt an AutoGen ``FunctionTool``-shaped object into a Maverick Tool.

    Duck-typed: needs ``name``, ``description``, and either ``run`` (async,
    AutoGen 0.4: ``run(args, cancellation_token)``) or a plain callable
    ``func``/``fn``. The 0.4 ``run`` path builds the args object from the
    tool's ``args_type`` when available, else passes the dict through.
    """
    name = str(getattr(autogen_tool, "name", "") or "autogen_tool")
    description = str(getattr(autogen_tool, "description", "") or name)

    def fn(args: dict[str, Any]) -> str:
        runner = getattr(autogen_tool, "run", None)
        if callable(runner):
            payload: Any = args
            args_type = getattr(autogen_tool, "args_type", None)
            if callable(args_type):
                try:
                    payload = args_type()(**args)
                except Exception:
                    payload = args
            try:
                out = asyncio.run(runner(payload, None))
            except TypeError:
                out = asyncio.run(runner(payload))
            return _result_text(out)
        call = getattr(autogen_tool, "func", None) or getattr(autogen_tool, "fn", None)
        if callable(call):
            return _result_text(call(**args))
        return "ERROR: AutoGen tool exposes neither run() nor func"

    return Tool(name=name, description=description,
                input_schema=_schema_or_default(autogen_tool), fn=fn)


def wrap_crewai_tool(crewai_tool: Any) -> Tool:
    """Adapt a CrewAI ``BaseTool``-shaped object into a Maverick Tool.

    Duck-typed: needs ``name``, ``description``, and ``_run`` (CrewAI's
    execution method) or ``run``.
    """
    name = str(getattr(crewai_tool, "name", "") or "crewai_tool")
    description = str(getattr(crewai_tool, "description", "") or name)

    def fn(args: dict[str, Any]) -> str:
        call = getattr(crewai_tool, "_run", None) or getattr(crewai_tool, "run", None)
        if not callable(call):
            return "ERROR: CrewAI tool exposes neither _run() nor run()"
        return _result_text(call(**args))

    return Tool(name=name, description=description,
                input_schema=_schema_or_default(crewai_tool), fn=fn)


__all__ = [
    "maverick_autogen_callable", "maverick_autogen_tool",
    "maverick_crewai_tool", "wrap_autogen_tool", "wrap_crewai_tool",
]
