"""Cross-repo dependency graph tool (roadmap: 2028 H1 capabilities).

Parses the Python import graph across one or more repo roots and surfaces the
edges *between* top-level packages — the view that matters when you're trying
to see how several repos (or several packages in a monorepo) actually couple to
each other, and whether that coupling has cycles.

ops:
  - graph(paths)   — package -> package edges (with file counts), plus which
                     edges cross from one given root into another.
  - cycles(paths)  — strongly-connected import cycles among the packages.

Read-only: it walks ``*.py`` files and parses them with ``ast`` (no import
execution). ``parallel_safe``.
"""
from __future__ import annotations

import ast
import os
from typing import Any

from . import Tool

_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".tox", "build", "dist"}


def _py_files(root: str) -> list[str]:
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for f in filenames:
            if f.endswith(".py"):
                out.append(os.path.join(dirpath, f))
    return out


def _top_package(path: str, root: str) -> str:
    """First path component of ``path`` relative to ``root`` (the package)."""
    rel = os.path.relpath(path, root)
    parts = rel.split(os.sep)
    return parts[0] if len(parts) > 1 else os.path.splitext(parts[0])[0]


def _imports(path: str) -> set[str]:
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except (SyntaxError, OSError):
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:  # absolute import only
                mods.add(node.module.split(".")[0])
    return mods


def _build(paths: list[str]) -> tuple[dict[tuple[str, str], int], dict[str, str]]:
    """Return (edges: (src_pkg,dst_pkg)->file_count, pkg->owning_root)."""
    pkg_root: dict[str, str] = {}
    local_pkgs: set[str] = set()
    files_by_root: dict[str, list[str]] = {}
    for root in paths:
        files = _py_files(root)
        files_by_root[root] = files
        for f in files:
            pkg = _top_package(f, root)
            local_pkgs.add(pkg)
            pkg_root.setdefault(pkg, root)

    edges: dict[tuple[str, str], int] = {}
    for root, files in files_by_root.items():
        for f in files:
            src = _top_package(f, root)
            for imp in _imports(f):
                if imp in local_pkgs and imp != src:
                    edges[(src, imp)] = edges.get((src, imp), 0) + 1
    return edges, pkg_root


def _cycles(edges: dict[tuple[str, str], int]) -> list[list[str]]:
    """Tarjan SCCs with >1 node (or a self-loop) = import cycles."""
    adj: dict[str, list[str]] = {}
    for (s, d) in edges:
        adj.setdefault(s, []).append(d)
        adj.setdefault(d, [])
    index = {}
    low = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = [0]
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in adj.get(v, []):
            if w not in index:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1 or (v, v) in edges:
                sccs.append(sorted(comp))

    for v in list(adj):
        if v not in index:
            strongconnect(v)
    return sccs


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    paths = [p for p in (args.get("paths") or []) if isinstance(p, str) and p.strip()]
    paths = [p for p in paths if os.path.isdir(p)]
    if not paths:
        return "ERROR: paths must include at least one existing directory"

    edges, pkg_root = _build(paths)
    if op == "graph":
        if not edges:
            return "no inter-package import edges found"
        rows = []
        for (s, d), n in sorted(edges.items(), key=lambda kv: (-kv[1], kv[0])):
            cross = "  [cross-root]" if pkg_root.get(s) != pkg_root.get(d) else ""
            rows.append(f"{s} -> {d}  ({n} import{'s' if n != 1 else ''}){cross}")
        return "\n".join(rows)
    if op == "cycles":
        cyc = _cycles(edges)
        if not cyc:
            return "no import cycles among packages"
        return "\n".join(" <-> ".join(c) for c in cyc)
    return f"ERROR: unknown op {op!r}"


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["graph", "cycles"]},
        "paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "one or more repo/package root directories to scan",
        },
    },
    "required": ["op", "paths"],
}


def cross_repo_deps() -> Tool:
    return Tool(
        name="cross_repo_deps",
        description=(
            "Cross-repo Python dependency graph. ops: graph (top-level "
            "package -> package import edges with counts; flags edges that "
            "cross from one root into another), cycles (import cycles among "
            "packages). Parses with ast, never executes imports. Pass one or "
            "more repo root dirs in 'paths'."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
