"""Clipboard tool.

Read from / write to the system clipboard. Useful for bridging between
computer-use / browser / shell flows ("copy this from the page into
the editor").

Intentionally host-local: the clipboard is a host-desktop resource, so
this tool shells out directly (with a scrubbed env) rather than through
``sandbox.exec`` — a sandboxed container has no access to the user's
clipboard. This is a deliberate exception to the "sandbox-mediate all
shell" rule, not an oversight.

Implementation strategy:
  1. ``pyperclip`` if installed (cross-platform, best UX)
  2. ``pbpaste`` / ``pbcopy`` (macOS)
  3. ``xclip`` / ``xsel`` (Linux X11)
  4. ``wl-paste`` / ``wl-copy`` (Linux Wayland)
  5. fail gracefully with install-hint
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_CLIPBOARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["read", "write"],
            "description": "Operation.",
        },
        "text": {"type": "string", "description": "Text to write (for write op)."},
    },
    "required": ["op"],
}


def _try_pyperclip_read() -> str | None:
    try:
        import pyperclip  # type: ignore
        return pyperclip.paste()
    except Exception:
        return None


def _try_pyperclip_write(text: str) -> bool:
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def _try_subprocess(cmd: list[str], stdin: str | None = None) -> str | None:
    """Run cmd; return stdout on success, None on failure."""
    if not shutil.which(cmd[0]):
        return None
    try:
        if stdin is not None:
            proc = subprocess.run(
                cmd, input=stdin.encode("utf-8"),
                capture_output=True, timeout=5,
            )
        else:
            proc = subprocess.run(cmd, capture_output=True, timeout=5)
        if proc.returncode != 0:
            return None
        return (proc.stdout or b"").decode("utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError) as e:
        log.debug("clipboard: %s failed: %s", cmd[0], e)
        return None


def _read_clipboard() -> str | None:
    val = _try_pyperclip_read()
    if val is not None:
        return val
    # macOS
    val = _try_subprocess(["pbpaste"])
    if val is not None:
        return val
    # Wayland
    val = _try_subprocess(["wl-paste"])
    if val is not None:
        return val
    # X11 (xclip)
    val = _try_subprocess(["xclip", "-selection", "clipboard", "-o"])
    if val is not None:
        return val
    # X11 (xsel)
    val = _try_subprocess(["xsel", "--clipboard", "--output"])
    if val is not None:
        return val
    return None


def _write_clipboard(text: str) -> bool:
    if _try_pyperclip_write(text):
        return True
    # macOS
    if shutil.which("pbcopy"):
        if _try_subprocess(["pbcopy"], stdin=text) is not None:
            return True
    # Wayland
    if shutil.which("wl-copy"):
        if _try_subprocess(["wl-copy"], stdin=text) is not None:
            return True
    # X11
    if shutil.which("xclip"):
        if _try_subprocess(["xclip", "-selection", "clipboard"], stdin=text) is not None:
            return True
    if shutil.which("xsel"):
        if _try_subprocess(["xsel", "--clipboard", "--input"], stdin=text) is not None:
            return True
    return False


def _run(args: dict[str, Any]) -> str:
    if os.environ.get("MAVERICK_CLIPBOARD_DISABLE") == "1":
        return "ERROR: clipboard tool disabled by MAVERICK_CLIPBOARD_DISABLE=1"
    op = args.get("op")
    if op == "read":
        val = _read_clipboard()
        if val is None:
            return (
                "ERROR: no clipboard backend available. Install one of: "
                "pyperclip (pip), xclip / xsel (X11), wl-clipboard (Wayland)."
            )
        return val
    if op == "write":
        text = args.get("text", "")
        if not isinstance(text, str):
            return "ERROR: write text must be a string"
        if _write_clipboard(text):
            return f"wrote {len(text)} chars to clipboard"
        return (
            "ERROR: no clipboard backend available. Install one of: "
            "pyperclip (pip), xclip / xsel (X11), wl-clipboard (Wayland)."
        )
    return f"ERROR: unknown op {op!r}"


def clipboard() -> Tool:
    return Tool(
        name="clipboard",
        description=(
            "Read or write the system clipboard. ops: read (returns "
            "current clipboard contents), write (sets clipboard to text). "
            "Useful for bridging between the browser/computer-use/shell "
            "tools and the user's editor. MAVERICK_CLIPBOARD_DISABLE=1 "
            "disables. Requires pyperclip OR xclip/xsel/wl-clipboard."
        ),
        input_schema=_CLIPBOARD_SCHEMA,
        fn=_run,
    )
