"""Persistent task graph: a dependency DAG of tasks you can resume.

A long-horizon run decomposes a goal into tasks with dependencies; this is the
durable structure that records them. The graph is a DAG — ``ready()`` returns the
frontier (pending tasks whose dependencies are all done) so a scheduler/swarm
knows what's runnable now, ``topo_order()`` gives a valid execution order, and a
dependency cycle is rejected (it would deadlock the frontier). State persists as
JSON so a killed run resumes where it left off.

``TaskGraph`` is the pure, unit-tested core; the ``task_graph`` tool persists one
named graph per file under ``~/.maverick/task_graphs/``.
"""
from __future__ import annotations

import json
from pathlib import Path

from .paths import data_dir

_STATUSES = ("pending", "running", "done", "failed", "blocked")
_STORE = data_dir("task_graphs")


class TaskGraph:
    def __init__(self) -> None:
        # id -> {"title": str, "deps": list[str], "status": str}
        self.tasks: dict[str, dict] = {}

    def add_task(self, task_id: str, title: str = "", deps=()) -> None:
        task_id = str(task_id).strip()
        if not task_id:
            raise ValueError("task id is required")
        deps = [str(d).strip() for d in deps if str(d).strip()]
        if task_id in deps:
            raise ValueError(f"task {task_id!r} cannot depend on itself")
        existing = self.tasks.get(task_id, {})
        self.tasks[task_id] = {
            "title": title or existing.get("title", ""),
            "deps": deps or existing.get("deps", []),
            "status": existing.get("status", "pending"),
        }

    def set_status(self, task_id: str, status: str) -> None:
        if status not in _STATUSES:
            raise ValueError(f"invalid status {status!r}; use one of {_STATUSES}")
        if task_id not in self.tasks:
            raise KeyError(f"no such task {task_id!r}")
        self.tasks[task_id]["status"] = status

    def ready(self) -> list[str]:
        """Pending tasks whose dependencies are all ``done`` (the frontier)."""
        out = []
        for tid, t in self.tasks.items():
            if t["status"] != "pending":
                continue
            if all(self.tasks.get(d, {}).get("status") == "done" for d in t["deps"]):
                out.append(tid)
        return sorted(out)

    def remaining_critical_weight(self, *, weights=None) -> dict[str, float]:
        """Per task, the heaviest chain of *not-yet-done* work from it onward
        (itself + its longest pending-descendant tail).

        This is the critical-path scheduling key: a ready task with a long
        remaining tail should start before one with a short tail, because the
        long-tail task bounds the finish time. ``done`` tasks contribute 0.
        Returns ``{task_id: remaining_weight}`` ({} on a cycle).
        """
        try:
            order = self.topo_order()
        except ValueError:
            return {}
        weights = weights or {}

        def w(tid: str) -> float:
            t = self.tasks.get(tid, {})
            if t.get("status") == "done":
                return 0.0
            try:
                return float(weights.get(tid, 1.0))
            except (TypeError, ValueError):
                return 1.0

        # children adjacency (a task -> tasks that depend on it)
        children: dict[str, list[str]] = {tid: [] for tid in self.tasks}
        for tid, t in self.tasks.items():
            for d in t.get("deps", []):
                if d in children:
                    children[d].append(tid)
        tail: dict[str, float] = {}
        for tid in reversed(order):  # dependents before deps
            best_child = max((tail.get(c, 0.0) for c in children.get(tid, [])),
                             default=0.0)
            tail[tid] = w(tid) + best_child
        return tail

    def ready_prioritized(self, *, weights=None) -> list[str]:
        """The ready frontier ordered by remaining critical weight (longest
        tail first) — the order a critical-path-aware scheduler dispatches.

        Ties broken by task id for determinism. Falls back to plain ``ready``
        order on a cycle (no critical weights available).
        """
        frontier = self.ready()
        tail = self.remaining_critical_weight(weights=weights)
        if not tail:
            return frontier
        return sorted(frontier, key=lambda tid: (-tail.get(tid, 0.0), tid))

    def has_cycle(self) -> bool:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = dict.fromkeys(self.tasks, WHITE)

        def visit(node: str) -> bool:
            color[node] = GRAY
            for dep in self.tasks.get(node, {}).get("deps", []):
                if dep not in color:
                    continue  # unknown dep can't form a cycle within the graph
                if color[dep] == GRAY:
                    return True
                if color[dep] == WHITE and visit(dep):
                    return True
            color[node] = BLACK
            return False

        return any(color[tid] == WHITE and visit(tid) for tid in self.tasks)

    def topo_order(self) -> list[str]:
        """A dependency-respecting order (deps before dependents).

        Raises ``ValueError`` on a cycle. Ties broken alphabetically so the
        order is deterministic.
        """
        if self.has_cycle():
            raise ValueError("task graph has a dependency cycle")
        order: list[str] = []
        done: set[str] = set()
        remaining = set(self.tasks)
        while remaining:
            avail = sorted(
                t for t in remaining
                if all(d in done or d not in self.tasks for d in self.tasks[t]["deps"]))
            if not avail:  # pragma: no cover -- guarded by has_cycle above
                raise ValueError("task graph has a dependency cycle")
            for t in avail:
                order.append(t)
                done.add(t)
                remaining.discard(t)
        return order

    def critical_path(self, *, weights=None) -> tuple[list[str], float]:
        """The longest dependency chain — the **critical path** that bounds how
        fast the graph can finish no matter how much you parallelize.

        ``weights`` is an optional ``{task_id: cost}`` (default 1.0 each), so the
        path is the heaviest chain when task durations are known. Returns
        ``(path_ids, total_weight)``; empty on a cycle or empty graph. The tasks
        on this path are the ones a critical-path-aware scheduler runs first.
        """
        try:
            order = self.topo_order()  # deps before dependents
        except ValueError:
            return [], 0.0
        weights = weights or {}

        def w(tid: str) -> float:
            try:
                return float(weights.get(tid, 1.0))
            except (TypeError, ValueError):
                return 1.0

        dist: dict[str, float] = {}
        prev: dict[str, str | None] = {}
        for tid in order:
            best, best_dep = 0.0, None
            for d in self.tasks.get(tid, {}).get("deps", []):
                if d in self.tasks and dist.get(d, 0.0) > best:
                    best, best_dep = dist[d], d
            dist[tid] = best + w(tid)
            prev[tid] = best_dep
        if not dist:
            return [], 0.0
        end = max(dist, key=lambda k: (dist[k], k))
        path: list[str] = []
        cur: str | None = end
        while cur is not None:
            path.append(cur)
            cur = prev.get(cur)
        path.reverse()
        return path, round(dist[end], 4)

    def to_dict(self) -> dict:
        return {"tasks": self.tasks}

    @classmethod
    def from_dict(cls, data: dict) -> TaskGraph:
        g = cls()
        g.tasks = {k: {"title": v.get("title", ""),
                       "deps": list(v.get("deps", [])),
                       "status": v.get("status", "pending")}
                   for k, v in (data.get("tasks") or {}).items()}
        return g

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> TaskGraph:
        p = Path(path)
        if not p.exists():
            return cls()
        return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))


# --- tool surface ----------------------------------------------------------

def _graph_path(name: str) -> Path:
    safe = "".join(c for c in (name or "default") if c.isalnum() or c in "-_") or "default"
    return _STORE / f"{safe}.json"


_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": "string",
               "enum": ["add", "status", "ready", "order", "list", "critical",
                        "schedule"]},
        "graph": {"type": "string", "description": "named graph (default 'default')"},
        "task": {"type": "string", "description": "task id"},
        "title": {"type": "string"},
        "deps": {"type": "array", "items": {"type": "string"}},
        "value": {"type": "string",
                  "description": "new status for the 'status' op"},
    },
    "required": ["op"],
}


def _run(args: dict) -> str:
    op = args.get("op")
    path = _graph_path(args.get("graph") or "default")
    try:
        g = TaskGraph.load(path)
        if op == "add":
            g.add_task(args.get("task") or "", args.get("title") or "",
                       args.get("deps") or [])
            g.save(path)
            return f"added task {args.get('task')!r}"
        if op == "status":
            g.set_status(args.get("task") or "", args.get("value") or "")
            g.save(path)
            return f"task {args.get('task')!r} -> {args.get('value')}"
        if op == "ready":
            r = g.ready()
            return "\n".join(r) if r else "(no ready tasks)"
        if op == "order":
            return "\n".join(g.topo_order()) or "(empty graph)"
        if op == "list":
            return json.dumps(g.to_dict()["tasks"], indent=2) if g.tasks else "(empty)"
        if op == "critical":
            path, length = g.critical_path()
            if not path:
                return "(no critical path — empty graph or a cycle)"
            return f"critical path ({len(path)} task(s), weight {length:g}): " + \
                " -> ".join(path)
        if op == "schedule":
            order = g.ready_prioritized()
            if not order:
                return "(no ready tasks)"
            tail = g.remaining_critical_weight()
            return "dispatch order (critical-path first):\n" + "\n".join(
                f"  {tid}  (remaining weight {tail.get(tid, 0):g})" for tid in order)
    except (ValueError, KeyError) as e:
        return f"ERROR: {e}"
    return f"ERROR: unknown op {op!r}"


def task_graph():
    from .tools import Tool
    return Tool(
        name="task_graph",
        description=(
            "Persistent dependency graph of tasks (a DAG you can resume). ops: "
            "add (task, title, deps[]), status (task, value), ready (frontier of "
            "runnable tasks), order (topological), critical (the longest "
            "dependency chain — the critical path to schedule first), list. One "
            "named graph per file "
            "under ~/.maverick/task_graphs."
        ),
        input_schema=_SCHEMA,
        fn=_run,
    )


__all__ = ["TaskGraph", "task_graph"]
