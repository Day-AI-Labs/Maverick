"""memory: a model-curated, cross-session memory directory.

The Anthropic memory-tool pattern (A3): the agent maintains structured notes in
a persistent ``/memories`` directory it controls, so long-horizon work survives
context compaction and even a process restart. The model writes durable learnings
(project conventions, decisions, dead ends to avoid) and reads them back fresh in
a later turn or session.

Distinct from its neighbours:
  - ``kv_memory``         — goal-scoped key/value, world-model-backed, wiped per run.
  - ``recall_past_goals`` — read-only recall of prior *episodes*.
  - ``memory`` (this)     — a model-managed *filesystem* of long-term knowledge that
                            persists across goals and sessions.

Host-side by nature: like the world model, consent ledger, and audit log, this is
Maverick's own store (under ``~/.maverick/memory`` by default, override
``MAVERICK_MEMORY_DIR``), not workspace files, so it isn't sandbox-mediated. All
paths are confined to the memory root (no traversal / symlink escape) and per-file
+ total-size caps bound it. Memory content is model-curated and re-enters context
on ``view`` — treat it with the same care as any tool output.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import Tool

_MAX_FILE_BYTES = 262_144           # 256 KB per memory file
_MAX_TOTAL_BYTES = 16 * 1024 * 1024  # 16 MB across the whole memory dir
_MAX_VIEW_BYTES = 16_000


def _memory_root() -> Path:
    raw = os.environ.get("MAVERICK_MEMORY_DIR")
    root = Path(raw).expanduser() if raw else Path.home() / ".maverick" / "memory"
    return root


def _resolve(root: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``root``, rejecting any escape.

    Accepts a leading ``/memories/`` or ``/`` (Anthropic clients send absolute-
    looking memory paths) by treating everything as relative to the root.
    ``.resolve()`` collapses ``..`` and follows symlinks, so a traversal or a
    symlink pointing outside the root lands outside and is refused."""
    cleaned = (rel or "").strip()
    for prefix in ("/memories/", "memories/", "/"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    target = (root / cleaned).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"path {rel!r} escapes the memory directory")
    return target


def _rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root)) or "."
    except ValueError:  # pragma: no cover -- _resolve already confined it
        return str(p)


def _dir_size(root: Path) -> int:
    total = 0
    for p in root.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:  # pragma: no cover -- racy unlink
            pass
    return total


def _view(target: Path, root: Path) -> str:
    if target.is_dir():
        rows: list[str] = []
        for p in sorted(target.rglob("*")):
            if p.is_file():
                try:
                    sz = p.stat().st_size
                except OSError:  # pragma: no cover
                    sz = 0
                rows.append(f"- {_rel(p, root)}  ({sz} bytes)")
        return "\n".join(rows) if rows else "(memory is empty)"
    try:
        data = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"ERROR: {e}"
    lines = data.splitlines()
    width = len(str(len(lines))) if lines else 1
    numbered = "\n".join(f"{i:>{width}}: {ln}" for i, ln in enumerate(lines, start=1))
    if len(numbered) > _MAX_VIEW_BYTES:
        return (numbered[:_MAX_VIEW_BYTES]
                + f"\n... [truncated at {_MAX_VIEW_BYTES} bytes; "
                + f"file is {len(lines)} lines total]")
    return numbered


def _fits(root: Path, target: Path, new_text: str) -> str | None:
    """Return an error string if writing ``new_text`` would bust a cap, else None."""
    size = len(new_text.encode("utf-8"))
    if size > _MAX_FILE_BYTES:
        return (f"ERROR: file too large ({size} bytes; max {_MAX_FILE_BYTES}). "
                "Split it or store a summary.")
    existing = target.stat().st_size if target.is_file() else 0
    if _dir_size(root) - existing + size > _MAX_TOTAL_BYTES:
        return (f"ERROR: memory is full (max {_MAX_TOTAL_BYTES} bytes total). "
                "Delete stale files first.")
    return None


def _run(args: dict) -> str:
    cmd = (args.get("command") or "").strip()
    if not cmd:
        return ("ERROR: missing `command` (view, create, str_replace, insert, "
                "delete, rename)")
    root = _memory_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"ERROR: cannot open memory directory: {e}"

    if cmd == "rename":
        try:
            src = _resolve(root, args.get("old_path") or args.get("path") or "")
            dst = _resolve(root, args.get("new_path") or "")
        except ValueError as e:
            return f"ERROR: {e}"
        if dst == root:
            return "ERROR: rename requires a `new_path`"
        if not src.exists():
            return f"ERROR: {_rel(src, root)} not found"
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
        except OSError as e:
            return f"ERROR: {e}"
        return f"renamed {_rel(src, root)} -> {_rel(dst, root)}"

    try:
        target = _resolve(root, args.get("path") or "")
    except ValueError as e:
        return f"ERROR: {e}"

    if cmd == "view":
        if not target.exists():
            if target == root:
                return "(memory is empty)"
            return f"ERROR: {_rel(target, root)} not found"
        return _view(target, root)

    if cmd == "create":
        if target == root:
            return "ERROR: create requires a file `path`"
        text = args.get("file_text") or args.get("content") or ""
        err = _fits(root, target, text)
        if err:
            return err
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        except OSError as e:
            return f"ERROR: {e}"
        return f"wrote {_rel(target, root)} ({len(text)} bytes)"

    if cmd == "str_replace":
        old = args.get("old_str")
        new = args.get("new_str")
        if old is None or new is None:
            return "ERROR: str_replace requires `old_str` and `new_str`"
        if not target.is_file():
            return f"ERROR: {_rel(target, root)} not found"
        data = target.read_text(encoding="utf-8", errors="replace")
        count = data.count(old)
        if count == 0:
            return ("ERROR: `old_str` not found. Use `view` to confirm the exact "
                    "text before retrying.")
        if count > 1:
            return (f"ERROR: `old_str` is ambiguous ({count} matches). Add "
                    "surrounding context so exactly one remains.")
        new_data = data.replace(old, new, 1)
        err = _fits(root, target, new_data)
        if err:
            return err
        try:
            target.write_text(new_data, encoding="utf-8")
        except OSError as e:
            return f"ERROR: {e}"
        delta = len(new_data) - len(data)
        return f"edited {_rel(target, root)} ({'+' if delta >= 0 else ''}{delta} bytes)"

    if cmd == "insert":
        after = args.get("insert_line")
        text = args.get("insert_text")
        if text is None:
            text = args.get("new_str", "")
        if after is None:
            return "ERROR: insert requires `insert_line` (0 = before first line)"
        if not target.is_file():
            return f"ERROR: {_rel(target, root)} not found"
        try:
            idx = int(after)
        except (TypeError, ValueError):
            return f"ERROR: insert_line must be an integer; got {after!r}"
        data = target.read_text(encoding="utf-8", errors="replace")
        lines = data.split("\n")
        if idx < 0 or idx > len(lines):
            return (f"ERROR: insert_line={idx} out of range "
                    f"(file has {len(lines)} lines; 0 = before first line)")
        new_data = "\n".join(lines[:idx] + text.split("\n") + lines[idx:])
        err = _fits(root, target, new_data)
        if err:
            return err
        try:
            target.write_text(new_data, encoding="utf-8")
        except OSError as e:
            return f"ERROR: {e}"
        return f"inserted at line {idx} of {_rel(target, root)}"

    if cmd == "delete":
        if target == root:
            return "ERROR: refusing to delete the memory root"
        if not target.exists():
            return f"ERROR: {_rel(target, root)} not found"
        try:
            if target.is_dir():
                target.rmdir()  # only empty dirs; refuses a non-empty tree
            else:
                target.unlink()
        except OSError as e:
            return f"ERROR: {e}"
        return f"deleted {_rel(target, root)}"

    return (f"ERROR: unknown command {cmd!r}; expected view, create, str_replace, "
            "insert, delete, or rename")


def memory_brief(*, max_chars: int = 2000) -> str:
    """A concise, promptable map of long-term memory for run bootstrap.

    Lists the memory files plus the model's curated index (``index.md`` /
    ``README.md``) if present, so a run starts already aware of what it knows.
    Returns ``""`` when memory is empty (the common case -> zero prompt change).

    Deliberately a small *map*, not a context dump: full file contents are read
    on demand via the tool's ``view``, which bounds both tokens and the
    prompt-injection surface (only filenames + a self-authored index land in the
    system prompt)."""
    root = _memory_root()
    try:
        files = sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []
    except OSError:  # pragma: no cover -- unreadable memory dir
        files = []
    if not files:
        return ""
    lines = [
        "## Your long-term memory",
        "Notes you saved in earlier sessions. Use the `memory` tool to `view` "
        "any file for detail, and to record durable learnings as you work.",
        "",
        "Files:",
    ]
    for p in files:
        try:
            sz = p.stat().st_size
        except OSError:  # pragma: no cover
            sz = 0
        lines.append(f"- {_rel(p, root)} ({sz} bytes)")
    for idx_name in ("index.md", "INDEX.md", "README.md"):
        idx = root / idx_name
        if idx.is_file():
            try:
                content = idx.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:  # pragma: no cover
                content = ""
            if content:
                lines += ["", f"--- {idx_name} (your index) ---", content]
            break
    brief = "\n".join(lines)
    if len(brief) > max_chars:
        brief = (brief[:max_chars].rstrip()
                 + "\n... [memory index truncated; `memory` view for the rest]")
    return brief


def memory() -> Tool:
    """Build the cross-session memory tool (confined to the memory root)."""
    return Tool(
        name="memory",
        description=(
            "Your durable, cross-session memory: a small filesystem of notes you "
            "curate and that survives context compaction and restarts. Use it for "
            "long-horizon knowledge worth keeping (project conventions, decisions, "
            "dead ends to avoid, a running plan) — NOT scratch data. Check it at "
            "the start of non-trivial work and update it as you learn. Commands: "
            "`view` (read a file with line numbers, or list memory when path is a "
            "dir/omitted); `create` (write/overwrite a file); `str_replace` "
            "(replace exactly-one occurrence); `insert` (after a line); `delete`; "
            "`rename`. Distinct from kv_memory (per-goal scratch) and "
            "recall_past_goals (read-only history)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["view", "create", "str_replace", "insert",
                             "delete", "rename"],
                },
                "path": {"type": "string",
                         "description": "Memory file/dir path (relative to your memory root)."},
                "file_text": {"type": "string", "description": "Content for `create`."},
                "old_str": {"type": "string", "description": "Exact text to replace (str_replace)."},
                "new_str": {"type": "string", "description": "Replacement text (str_replace)."},
                "insert_line": {"type": "integer",
                                "description": "1-based line to insert AFTER (0 = top)."},
                "insert_text": {"type": "string", "description": "Text to insert (insert)."},
                "old_path": {"type": "string", "description": "Source path (rename)."},
                "new_path": {"type": "string", "description": "Destination path (rename)."},
            },
            "required": ["command"],
        },
        fn=_run,
    )


__all__ = ["memory", "memory_brief"]
