"""Semantic-ish code search tool (roadmap: 2028 H1 capabilities).

Indexes the functions and classes under one or more paths (via ``ast``, no
import execution) and ranks them against a natural-language query using a
zero-dependency lexical scorer over each symbol's name, signature, and
docstring. "Semantic-ish": it understands code *structure* (it searches
symbols, not raw lines) and tolerates word-order/identifier-style differences
(snake/camel are split into words), without needing an embedding model. When a
vector store is wired in elsewhere it can be swapped for true embeddings; this
is the always-available default, mirroring the long-context router's design.

ops:
  - search(paths, query[, k])  — top-k matching symbols as ``file:line  qualname``.

Read-only, ``parallel_safe``.
"""
from __future__ import annotations

import ast
import os
import re
from typing import Any

from . import Tool

_SKIP = {".git", "__pycache__", ".venv", "venv", "node_modules", ".tox", "build", "dist"}
_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    # Split identifiers: snake_case and camelCase both become word lists.
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text or "")
    return _WORD.findall(spaced.lower())


def _py_files(root: str) -> list[str]:
    out: list[str] = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in _SKIP]
        out.extend(os.path.join(dp, f) for f in fns if f.endswith(".py"))
    return out


def _signature(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return ", ".join(a.arg for a in node.args.args)
    return ""


def _symbols(path: str) -> list[tuple[str, int, str]]:
    """(qualname, lineno, indexed_text) for each top-level/nested def/class."""
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except (SyntaxError, OSError):
        return []
    out: list[tuple[str, int, str]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = f"{prefix}{child.name}"
                doc = ast.get_docstring(child) or ""
                text = " ".join([child.name, _signature(child), doc])
                out.append((qual, child.lineno, text))
                visit(child, qual + ".")

    visit(tree, "")
    return out


def _score(query_words: list[str], text_words: list[str]) -> float:
    if not query_words or not text_words:
        return 0.0
    tset = set(text_words)
    hits = sum(1 for q in query_words if q in tset)
    return hits / len(query_words)


def _run(args: dict[str, Any]) -> str:
    if args.get("op") not in (None, "search"):
        return f"ERROR: unknown op {args.get('op')!r}"
    query = (args.get("query") or "").strip()
    if not query:
        return "ERROR: query is required"
    paths = [p for p in (args.get("paths") or []) if isinstance(p, str) and os.path.exists(p)]
    if not paths:
        return "ERROR: paths must include at least one existing file or directory"
    try:
        k = int(args.get("k", 10))
    except (TypeError, ValueError):
        k = 10
    k = max(1, min(k, 50))

    qwords = _words(query)
    scored: list[tuple[float, str, int, str]] = []
    files: list[str] = []
    for p in paths:
        files.extend(_py_files(p) if os.path.isdir(p) else [p])
    for f in files:
        for qual, line, text in _symbols(f):
            s = _score(qwords, _words(text))
            if s > 0:
                scored.append((s, f, line, qual))

    if not scored:
        return f"no symbols matched {query!r}"
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    rows = [f"{s:.2f}  {f}:{line}  {qual}" for s, f, line, qual in scored[:k]]
    return "\n".join(rows)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["search"]},
        "paths": {"type": "array", "items": {"type": "string"},
                  "description": "files/dirs to index"},
        "query": {"type": "string", "description": "natural-language description of the code"},
        "k": {"type": "integer", "description": "max results (default 10)"},
    },
    "required": ["query", "paths"],
}


def semantic_code_search() -> Tool:
    return Tool(
        name="semantic_code_search",
        description=(
            "Search code by intent, not regex. Indexes functions/classes under "
            "the given paths (ast; no execution) and ranks them against a "
            "natural-language query over each symbol's name, signature, and "
            "docstring, splitting snake_case/camelCase into words. Returns "
            "top-k 'score  file:line  qualname'. Zero-dependency lexical "
            "default (swap in embeddings via a vector store elsewhere)."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
