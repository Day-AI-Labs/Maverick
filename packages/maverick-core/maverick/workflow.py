"""Workflow engine — chain tool calls into a DAG.

A workflow is a list of `Step` nodes; each step names a tool, supplies
its args (which may reference outputs from earlier steps), and declares
optional dependencies. The engine resolves the DAG, runs ready steps,
records each step's output, and lets you reference prior outputs via a
``${step_name.out}`` placeholder inside string args.

This is intentionally tiny — no checkpointing, no resume, no rollback.
It's the "glue" piece that lets the agent (or a power user) compose 3-7
existing tools into a one-shot workflow without spawning a sub-agent.

Use:

    from maverick.workflow import Step, Workflow

    wf = Workflow(steps=[
        Step("fetch", "http_fetch", {"url": "https://news.ycombinator.com"}),
        Step("snap",  "ocr",        {"op": "extract_url", "url": "${fetch.url}"}),
        Step("note",  "notify",     {"title": "OCR done",
                                       "body": "${snap.out}"}),
    ])
    result = wf.run(registry)

Cycles are rejected at construction. Output of each step is whatever
the underlying tool returned (string).
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][\w]*)\.out\}")


@dataclass
class Step:
    name: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class StepResult:
    name: str
    tool: str
    ok: bool
    output: str
    error: str = ""
    elapsed_ms: float = 0.0


@dataclass
class WorkflowResult:
    steps: list[StepResult] = field(default_factory=list)
    failed: bool = False

    def by_name(self) -> dict[str, StepResult]:
        return {s.name: s for s in self.steps}


class WorkflowCycle(Exception):
    """Raised when a workflow's depends_on creates a cycle."""


class Workflow:
    def __init__(self, steps: list[Step]) -> None:
        if not steps:
            raise ValueError("workflow requires at least one step")
        seen: set[str] = set()
        for s in steps:
            if s.name in seen:
                raise ValueError(f"duplicate step name {s.name!r}")
            seen.add(s.name)
        self.steps = list(steps)
        # Validate dependency graph + detect cycles.
        self._topo_order = self._topo_sort()

    def _all_deps(self, step: Step, known: set[str]) -> list[str]:
        # Explicit deps + implicit string-template deps.
        deps = set(step.depends_on)
        for v in step.args.values():
            if isinstance(v, str):
                deps |= {m.group(1) for m in _PLACEHOLDER.finditer(v)}
        unknown = [d for d in deps if d not in known]
        if unknown:
            raise ValueError(
                f"step {step.name!r}: unknown dependency {unknown}"
            )
        return sorted(deps)

    def _topo_sort(self) -> list[Step]:
        names = {s.name for s in self.steps}
        # Build forward-dep map.
        forward: dict[str, set[str]] = {s.name: set() for s in self.steps}
        for s in self.steps:
            for d in self._all_deps(s, names):
                if d == s.name:
                    raise WorkflowCycle(f"step {s.name!r} depends on itself")
                forward[d].add(s.name)
        in_deg: dict[str, int] = {
            s.name: len(self._all_deps(s, names)) for s in self.steps
        }
        ready = [s for s in self.steps if in_deg[s.name] == 0]
        order: list[Step] = []
        by_name = {s.name: s for s in self.steps}
        while ready:
            nxt = ready.pop(0)
            order.append(nxt)
            for child in forward[nxt.name]:
                in_deg[child] -= 1
                if in_deg[child] == 0:
                    ready.append(by_name[child])
        if len(order) != len(self.steps):
            unresolved = [s.name for s in self.steps if in_deg[s.name] > 0]
            raise WorkflowCycle(f"cycle involving {unresolved}")
        return order

    def _interpolate(self, value: Any, outputs: dict[str, str]) -> Any:
        if isinstance(value, str):
            return _PLACEHOLDER.sub(
                lambda m: outputs.get(m.group(1), m.group(0)),
                value,
            )
        if isinstance(value, dict):
            return {k: self._interpolate(v, outputs) for k, v in value.items()}
        if isinstance(value, list):
            return [self._interpolate(v, outputs) for v in value]
        return value

    def run(
        self,
        registry,
        *,
        stop_on_error: bool = True,
    ) -> WorkflowResult:
        import time
        result = WorkflowResult()
        outputs: dict[str, str] = {}
        for step in self._topo_order:
            args = self._interpolate(step.args, outputs)
            t0 = time.time()
            try:
                raw = _drive(registry.run(step.tool, args))
                ok = not str(raw).startswith("ERROR:")
                err = "" if ok else str(raw)
            except Exception as e:
                raw = ""
                ok = False
                err = f"{type(e).__name__}: {e}"
            elapsed_ms = (time.time() - t0) * 1000
            sr = StepResult(
                name=step.name, tool=step.tool, ok=ok,
                output=str(raw or ""), error=err, elapsed_ms=elapsed_ms,
            )
            result.steps.append(sr)
            if not ok:
                result.failed = True
                log.warning("workflow step %s failed: %s", step.name, err)
                if stop_on_error:
                    break
            outputs[step.name] = sr.output
        return result


def _drive(coro):
    """Run an awaitable to completion from a SYNC caller, whether or not
    an event loop is already running on this thread.

    ``asyncio.run`` raises "cannot be called from a running event loop"
    when invoked from inside async code (the agent kernel runs in a
    loop). When a loop is already running we off-load the coroutine to a
    dedicated thread with its own loop and block for the result; the
    short-lived thread keeps the workflow callable from both sync and
    async contexts.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


__all__ = [
    "Step", "StepResult", "Workflow", "WorkflowResult", "WorkflowCycle",
]
