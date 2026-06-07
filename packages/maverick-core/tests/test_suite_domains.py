"""Built-in business-suite domain packs (ops_*, legal_*): load + safety invariants.

These packs are the agents the factory spawns for the Operations and Legal suites.
Each must load, carry a persona + a sealed compartment, and -- because every one of
these agents *analyzes and drafts* but never acts on the world -- run under a
read-only, low/medium-risk capability envelope (deny wins; the whitelist excludes
shell/write). This test is the contract that keeps a new or edited pack from quietly
granting a dangerous tool.
"""
from __future__ import annotations

from maverick.domain import builtin_dir, load_domains

_BUILTIN = load_domains(builtin_dir())
_OPS = {k: v for k, v in _BUILTIN.items() if k.startswith("ops_")}
_LEGAL = {k: v for k, v in _BUILTIN.items() if k.startswith("legal_")}
_SUITE = {**_OPS, **_LEGAL}


def test_suites_present():
    # Operations is fully built (8 towers); legal_* packs are added alongside.
    assert len(_OPS) >= 39, f"expected >=39 Operations packs, found {len(_OPS)}"


def test_every_suite_pack_loads_with_persona_and_compartment():
    assert _SUITE, "no suite packs discovered"
    for name, p in _SUITE.items():
        assert p.name == name
        assert p.persona.strip(), f"{name}: empty persona"
        assert p.compartment, f"{name}: missing compartment"
        assert p.max_risk in ("low", "medium"), f"{name}: risk={p.max_risk!r}"


def test_suite_packs_are_read_only_and_safe():
    for name, p in _SUITE.items():
        cap = p.capability(f"agent:{name}")
        assert cap.permits("read_file") is True, f"{name}: cannot read"
        # Mutating / host-control tools must be unreachable (deny + whitelist + ceiling).
        for dangerous in ("shell", "write_file", "code_exec", "computer", "home_assistant"):
            assert cap.permits(dangerous) is False, f"{name}: {dangerous} reachable!"
        assert "shell" in p.deny_tools and "write_file" in p.deny_tools, (
            f"{name}: must explicitly deny shell + write_file"
        )


def test_ops_compartments_are_sealed_by_tower():
    # Every Operations pack sits in an ops_* compartment (the Rung-2 seal boundary).
    for name, p in _OPS.items():
        assert p.compartment.startswith("ops_"), f"{name}: compartment={p.compartment!r}"
