"""Self-edit tool: propose-only diffs for Maverick's own code / config.

The tool may inspect and propose exact-match changes to Maverick source or
``~/.maverick`` config, but it never writes files. A previous implementation
allowed ``apply`` with a model-supplied ``confirm=true`` flag; that is not a real
human approval channel because untrusted goals or prompt injection can influence
tool arguments. Guard rails, all enforced here:

  * **Path-confined**: only files under the maverick package root or
    ``~/.maverick`` can be diffed. Anything else is refused.
  * **Propose-only**: ``apply`` returns a dry-run diff even when ``confirm`` is
    true; a human/operator must copy the proposed patch through normal code
    review or workspace editing flows.
  * **Exact-match**: replaces a unique ``find`` substring; ambiguous or absent
    matches are rejected so a proposed edit can't target the wrong place.

``_allowed_roots`` is overridable so the confinement is unit-tested against a
tmp root.
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from . import Tool

_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["propose", "apply"]},
        "path": {"type": "string", "description": "file under the maverick pkg or ~/.maverick"},
        "find": {"type": "string", "description": "exact substring to replace (must be unique)"},
        "replace": {"type": "string", "description": "replacement text"},
        "confirm": {"type": "boolean",
                    "description": "accepted for compatibility; writes are disabled"},
    },
    "required": ["op", "path", "find", "replace"],
}


def _allowed_roots() -> list[Path]:
    """Roots a self-edit may touch: the maverick package + ~/.maverick."""
    pkg_root = Path(__file__).resolve().parent.parent  # .../maverick
    return [pkg_root, (Path.home() / ".maverick").resolve()]


def _confined(path: Path) -> bool:
    target = path.resolve()
    for root in _allowed_roots():
        root = root.resolve()
        if target == root or root in target.parents:
            return True
    return False


def _diff(path: Path, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{path.name}", tofile=f"b/{path.name}"))


def _apply_edit(text: str, find: str, replace: str) -> tuple[str | None, str]:
    """Return (new_text, message). new_text is None on a rejectable condition."""
    count = text.count(find)
    if count == 0:
        return None, "ERROR: 'find' text not present in file"
    if count > 1:
        return None, f"ERROR: 'find' text is ambiguous (matches {count}x); make it unique"
    return text.replace(find, replace, 1), "ok"


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    path = Path((args.get("path") or "").strip()).expanduser()
    find = args.get("find") or ""
    replace = args.get("replace")
    if replace is None:
        return "ERROR: 'replace' is required"
    if not _confined(path):
        return ("ERROR: refusing to edit outside the maverick package or "
                "~/.maverick (self-edit is path-confined)")
    if not path.exists():
        return f"ERROR: no such file {path}"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return f"ERROR: cannot read {path}: {e}"

    new_text, msg = _apply_edit(text, find, replace)
    if new_text is None:
        return msg
    diff = _diff(path, text, new_text) or "(no textual change)"

    if op == "propose":
        return f"PROPOSED edit to {path} (not applied):\n{diff}"
    if op == "apply":
        return (
            f"DRY RUN — self_edit cannot write files; proposed edit to {path}:\n{diff}\n"
            "Apply this change outside the agent tool path after human review."
        )
    return f"ERROR: unknown op {op!r}"


def self_edit() -> Tool:
    return Tool(
        name="self_edit",
        description=(
            "Propose an exact-match edit to Maverick's own code or config "
            "(path-confined to the maverick package + ~/.maverick). Writes are "
            "disabled: propose/apply both return diffs for human review only."
        ),
        input_schema=_SCHEMA,
        fn=_run,
    )


__all__ = ["self_edit", "_allowed_roots", "_apply_edit"]
