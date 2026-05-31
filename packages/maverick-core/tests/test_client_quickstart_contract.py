"""Client quickstarts must match the MCP server's real tool surface.

docs/clients/{typescript,go,rust}-quickstart.md are the cross-language examples
for driving Maverick over MCP. They're only "runnable" if the tools they call
actually exist with the documented names/args. If anyone renames, removes, or
adds a tool in maverick_mcp.server.TOOLS, these fail so the docs get updated
instead of silently shipping a copy-paste example that calls a missing tool.

This is the language-agnostic "tested" half of the client bindings: it runs in
the Python CI (introspecting the server) without needing Node/Go/Rust toolchains.
"""
from __future__ import annotations

import re
from pathlib import Path

from maverick_mcp.server import TOOLS

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TOOL_NAMES = {t["name"] for t in TOOLS}
_QUICKSTARTS = ("typescript", "go", "rust")


def _doc(lang: str) -> str:
    p = _REPO_ROOT / "docs" / "clients" / f"{lang}-quickstart.md"
    assert p.exists(), f"missing docs/clients/{lang}-quickstart.md"
    return p.read_text(encoding="utf-8")


def test_quickstarts_only_reference_real_tools():
    """No quickstart may reference a maverick_* tool the server doesn't expose."""
    for lang in _QUICKSTARTS:
        referenced = set(re.findall(r"\bmaverick_[a-z_]+\b", _doc(lang)))
        missing = referenced - _TOOL_NAMES
        assert not missing, f"{lang}-quickstart.md calls unknown MCP tools: {sorted(missing)}"


def test_typescript_quickstart_documents_every_tool():
    """The TS quickstart is the canonical surface doc -> it must name every
    tool, so adding one to the server forces a doc update."""
    text = _doc("typescript")
    undocumented = sorted(n for n in _TOOL_NAMES if n not in text)
    assert not undocumented, f"typescript-quickstart.md omits MCP tools: {undocumented}"


def test_typescript_quickstart_tool_count_is_accurate():
    """The doc states a tool count; keep it honest against TOOLS."""
    text = _doc("typescript")
    assert re.search(rf"\b{len(TOOLS)}\b[^\n]*tools", text), (
        f"typescript-quickstart.md should state the real tool count ({len(TOOLS)})"
    )


def test_maverick_start_documented_args_are_real():
    """The TS example calls maverick_start with title/description/max_dollars;
    those must be real input properties or the example won't work."""
    start = next(t for t in TOOLS if t["name"] == "maverick_start")
    props = set((start.get("inputSchema") or {}).get("properties", {}))
    for arg in ("title", "description", "max_dollars"):
        assert arg in props, f"maverick_start schema is missing documented arg '{arg}'"
