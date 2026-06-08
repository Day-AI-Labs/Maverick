"""A glob `[security.tool_risk]` override must not silently *lower* a built-in
risk classification: built-in risk is a floor that only an exact override can
drop. This closes the footgun where a broad wildcard (e.g. ``"s*" = "low"``)
declassifies dangerous built-ins like ``shell`` / ``wire_transfer``, defeating
max_risk ceilings and the governance risk gate.
"""
from __future__ import annotations

from maverick.safety.tool_risk import tool_risk


def test_glob_cannot_lower_builtin_high():
    # A wildcard that would declassify a built-in HIGH tool is clamped to the
    # built-in floor.
    assert tool_risk("shell", {"s*": "low"}) == "high"
    assert tool_risk("wire_transfer", {"wire_*": "low"}) == "high"
    assert tool_risk("release_payment", {"*": "low"}) == "high"


def test_exact_override_still_lowers_builtin():
    # An explicit, exact operator decision is honored (precise intent).
    assert tool_risk("shell", {"shell": "low"}) == "low"
    assert tool_risk("wire_transfer", {"wire_transfer": "medium"}) == "medium"


def test_glob_can_still_raise_and_relax_non_builtins():
    # A glob may RAISE a built-in...
    assert tool_risk("read_file", {"read_*": "high"}) == "high"
    # ...and may still relax a non-built-in fail-safe (mcp_*), the documented
    # use case -- mcp tools are not in the built-in table, so no floor applies.
    assert tool_risk("mcp_other__write", {"mcp_*": "medium"}) == "medium"
    # An unknown tool is classified freely by a glob.
    assert tool_risk("acme_custom_tool", {"acme_*": "low"}) == "low"
