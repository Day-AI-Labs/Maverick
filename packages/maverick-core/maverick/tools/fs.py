"""Filesystem tools backed by the sandbox.

v0.1.1 fix: ``read_file`` / ``list_dir`` no longer interpolate the
LLM-supplied path into a shell command. They use ``pathlib`` directly
and verify the resolved path stays inside the sandbox workdir.

``write_file`` already used pathlib; tightened the path-traversal
check to match.

The shell tool (`shell.py`) intentionally exposes shell execution —
that's its purpose. Shield's `scan_tool_call` chokepoint guards it.
"""
from __future__ import annotations

from pathlib import Path

from . import Tool


MAX_READ_BYTES = 8000


def _safe_resolve(sandbox, user_path: str) -> Path:
    """Resolve `user_path` relative to sandbox.workdir, refusing traversal.

    Raises ValueError if the resolved path escapes the workspace.
    """
    workdir = Path(sandbox.workdir).resolve()
    candidate = (workdir / user_path).resolve()
    try:
        candidate.relative_to(workdir)
    except ValueError as e:
        raise ValueError(
            f"path {user_path!r} escapes the workspace"
        ) from e
    return candidate


def _is_test_path(rel_path: str) -> bool:
    """Heuristic: is this path a test file the benchmark grader uses?

    Wave 10 (S1): we block read access to these in opaque benchmark
    mode so the agent can't hardcode to gold expected values it spied
    in the assertion bodies.

    Wave 12 hardening pass: any path UNDER a tests/ directory is
    blocked, not just files that match the test-naming heuristic. The
    prior rule (file matches test_*.py AND lives in tests/) left
    tests/conftest.py, tests/__init__.py, tests/helpers.py, and the
    FAIL_TO_PASS support files readable — these typically contain the
    expected-value tables and parametrize IDs the agent must not see.
    """
    p = rel_path.lower().replace("\\", "/")
    parts = [x for x in p.split("/") if x]
    name = parts[-1] if parts else ""
    in_test_dir = any(seg in {"tests", "test", "__tests__", "spec", "specs"}
                      for seg in parts[:-1])
    # Wave 12: ANY file under tests/ is gated.
    if in_test_dir:
        return True
    test_file = (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.js")
        or name.endswith(".test.ts")
        or name.endswith(".spec.js")
        or name.endswith(".spec.ts")
        or name.endswith("test.go")
        or name.endswith("_spec.rb")
        or name.endswith("Test.java")
        or name.endswith("Tests.java")
    )
    return test_file


def _is_dotgit_path(rel_path: str) -> bool:
    """Wave 12 (council F9d): block reads under `.git/`.

    The .git directory leaks the gold answer via refs/objects:
      - `.git/refs/heads/main` → gold commit SHA
      - `.git/objects/<sha>` → raw object contents (the patch)
      - `.git/HEAD`, `.git/packed-refs` → ref enumeration
    The shell tool already blocks `git log -p` / `git show` / `git
    cat-file`; this closes the corresponding file-read backdoor.
    """
    p = rel_path.replace("\\", "/")
    parts = [x for x in p.split("/") if x]
    return any(seg == ".git" for seg in parts)


def _is_opaque_blocked(rel_path: str) -> bool:
    """Return True if `rel_path` should be blocked under opaque benchmark
    mode. Combines the test-path and .git-path checks."""
    import os as _os
    opaque = _os.environ.get("MAVERICK_BENCHMARK_OPAQUE", "1") != "0"
    coding = _os.environ.get(
        "MAVERICK_CODING_MODE", ""
    ).lower() in ("1", "true", "yes")
    if not (opaque and coding):
        return False
    return _is_test_path(rel_path) or _is_dotgit_path(rel_path)


def _is_opaque_blocked_resolved(sandbox, rel_path: str) -> bool:
    """Wave 12 hardening pass: re-check the opacity gate on the CANONICAL
    resolved path so symlink trickery cannot bypass it.

    The raw-input check `_is_opaque_blocked(rel_path)` catches the
    direct case (`.git/HEAD`, `tests/test_foo.py`). But the agent
    could do `ln -s .git safe_dir` then `read_file("safe_dir/HEAD")` —
    raw input contains neither `.git` nor `tests/`. After
    `_safe_resolve` follows the symlink, we re-derive the workspace-
    relative form and re-run the gate so the canonical location is
    what's checked.
    """
    if _is_opaque_blocked(rel_path):
        return True
    try:
        workdir = Path(sandbox.workdir).resolve()
        candidate = (workdir / rel_path).resolve()
        rel = candidate.relative_to(workdir).as_posix()
    except (ValueError, OSError):
        # Can't resolve cleanly — let downstream _safe_resolve produce
        # the proper error.
        return False
    return _is_opaque_blocked(rel)


def read_file(sandbox) -> Tool:
    def fn(args: dict) -> str:
        path_arg = args["path"]
        # Wave 10 (S1) + Wave 12 (F9d) + Wave 12 hardening: block test
        # AND .git/ reads in opaque mode, on the CANONICAL resolved
        # path so symlinks can't bypass.
        if _is_opaque_blocked_resolved(sandbox, path_arg):
            if _is_dotgit_path(path_arg):
                return (
                    f"ERROR: read_file({path_arg!r}) blocked in benchmark "
                    "opaque mode. The .git directory leaks the gold "
                    "answer via refs/objects; derive your fix from the "
                    "code under test, not from git's internal storage. "
                    "(Override by setting MAVERICK_BENCHMARK_OPAQUE=0.)"
                )
            return (
                f"ERROR: read_file({path_arg!r}) blocked in benchmark "
                "opaque mode. The test files contain the grader's "
                "expected values; derive your fix from the production "
                "code under test, not from inspecting the assertions. "
                "(Override by setting MAVERICK_BENCHMARK_OPAQUE=0.)"
            )
        try:
            target = _safe_resolve(sandbox, path_arg)
        except ValueError as e:
            return f"ERROR: {e}"
        if not target.exists():
            return f"ERROR: {target} not found"
        if not target.is_file():
            return f"ERROR: {target} is not a file"
        try:
            data = target.read_text(encoding="utf-8", errors="replace")
        except (PermissionError, OSError) as e:
            return f"ERROR: {e}"
        if len(data) > MAX_READ_BYTES:
            return data[:MAX_READ_BYTES] + f"\n... [truncated, total {len(data)} bytes]"
        return data

    return Tool(
        name="read_file",
        description="Read a file from the workspace.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Path to read."}},
            "required": ["path"],
        },
        fn=fn,
    )


def write_file(sandbox) -> Tool:
    def fn(args: dict) -> str:
        try:
            target = _safe_resolve(sandbox, args["path"])
        except ValueError as e:
            return f"ERROR: {e}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args["content"], encoding="utf-8")
        except (PermissionError, OSError) as e:
            return f"ERROR: {e}"
        return f"wrote {len(args['content'])} bytes to {target}"

    return Tool(
        name="write_file",
        description="Write content to a file in the workspace. Overwrites if it exists.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        fn=fn,
    )


def list_dir(sandbox) -> Tool:
    def fn(args: dict) -> str:
        try:
            target = _safe_resolve(sandbox, args.get("path", "."))
        except ValueError as e:
            return f"ERROR: {e}"
        if not target.exists():
            return f"ERROR: {target} not found"
        if not target.is_dir():
            return f"ERROR: {target} is not a directory"
        entries = []
        try:
            for entry in sorted(target.iterdir()):
                kind = "d" if entry.is_dir() else "-"
                entries.append(f"{kind} {entry.name}")
        except (PermissionError, OSError) as e:
            return f"ERROR: {e}"
        return "\n".join(entries) if entries else "(empty)"

    return Tool(
        name="list_dir",
        description="List files in a directory.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
        },
        fn=fn,
    )
