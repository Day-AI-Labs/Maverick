"""Built-in business-suite domain packs: load + safety invariants.

These packs are the agents the factory spawns for the business suites (Operations,
Legal, IT-GRC, Sales/GTM, HR, Strategy, and Product&Engineering). Almost every agent
*analyzes and drafts* but never acts on the world, so it must load, carry a persona +
a sealed compartment, and run under a read-only, low/medium-risk capability envelope
(deny wins; the whitelist excludes shell/write). The exception is the
Product&Engineering *builders* -- coding agents that need sandbox-mediated
shell/code_exec -- which instead carry the one hard floor that can never relax: an
agent may build, but never modify its own runtime/safety/controls (``self_edit``
denied). This test is the contract that keeps a new or edited pack from quietly
granting a dangerous tool.
"""
from __future__ import annotations

from maverick.domain import builtin_dir, load_domains

_BUILTIN = load_domains(builtin_dir())


def _by_prefix(pre: str) -> dict:
    return {k: v for k, v in _BUILTIN.items() if k.startswith(pre)}


_OPS = _by_prefix("ops_")
_LEGAL = _by_prefix("legal_")
_ITGRC = _by_prefix("itgrc_")
_GTM = _by_prefix("gtm_")
_HR = _by_prefix("hr_")
_STRAT = _by_prefix("strat_")
_PE = _by_prefix("pe_")

# P&E splits into coding *builders* (sandbox shell/code_exec) and read-only seats.
_PE_BUILDERS = {k: v for k, v in _PE.items()
                if "code_exec" in v.allow_tools or "shell" in v.allow_tools}
_PE_READONLY = {k: v for k, v in _PE.items() if k not in _PE_BUILDERS}

# Every read-only/sealed pack across all suites obeys the same envelope.
_SUITE = {**_OPS, **_LEGAL, **_ITGRC, **_GTM, **_HR, **_STRAT, **_PE_READONLY}


def test_suites_present():
    # Each suite is fully built out as DomainProfile packs.
    assert len(_OPS) >= 39, f"expected >=39 Operations packs, found {len(_OPS)}"
    assert len(_LEGAL) >= 36, f"expected >=36 Legal packs, found {len(_LEGAL)}"
    assert len(_ITGRC) >= 55, f"expected >=55 IT-GRC packs, found {len(_ITGRC)}"
    assert len(_GTM) >= 50, f"expected >=50 Sales/GTM packs, found {len(_GTM)}"
    assert len(_HR) >= 46, f"expected >=46 HR packs, found {len(_HR)}"
    assert len(_STRAT) >= 31, f"expected >=31 Strategy packs, found {len(_STRAT)}"
    assert len(_PE) >= 46, f"expected >=46 Product&Eng packs, found {len(_PE)}"
    assert len(_PE_BUILDERS) >= 20, f"expected >=20 P&E builders, found {len(_PE_BUILDERS)}"


def test_every_suite_pack_loads_with_persona_and_compartment():
    assert _SUITE, "no suite packs discovered"
    for name, p in {**_SUITE, **_PE_BUILDERS}.items():
        assert p.name == name
        assert p.persona.strip(), f"{name}: empty persona"
        assert p.compartment, f"{name}: missing compartment"


def test_suite_packs_are_read_only_and_safe():
    for name, p in _SUITE.items():
        assert p.max_risk in ("low", "medium"), f"{name}: risk={p.max_risk!r}"
        cap = p.capability(f"agent:{name}")
        assert cap.permits("read_file") is True, f"{name}: cannot read"
        # Mutating / host-control tools must be unreachable (deny + whitelist + ceiling).
        for dangerous in ("shell", "write_file", "code_exec", "computer", "home_assistant"):
            assert cap.permits(dangerous) is False, f"{name}: {dangerous} reachable!"
        assert "shell" in p.deny_tools and "write_file" in p.deny_tools, (
            f"{name}: must explicitly deny shell + write_file"
        )


def test_strat_sealed_deal_execution_has_no_web_egress():
    # Deal-execution handles MNPI inside the sealed corp-dev compartment. Unlike
    # target sourcing, it only uses the deal compartment and legal/knowledge inputs,
    # so model-controlled web_search queries must be explicitly unreachable.
    p = _STRAT["strat_deal_execution"]
    cap = p.capability("agent:strat_deal_execution")
    assert "web_search" not in p.allow_tools
    assert "web_search" in p.deny_tools
    assert cap.permits("web_search") is False


def test_pe_builders_can_build_but_never_self_edit():
    # P&E coding agents legitimately need sandbox shell/code_exec; the floor that can
    # never relax is self-modification -- an agent never edits its own runtime/safety.
    assert _PE_BUILDERS, "no P&E builder packs discovered"
    for name, p in _PE_BUILDERS.items():
        cap = p.capability(f"agent:{name}")
        assert cap.permits("read_file") is True, f"{name}: cannot read"
        assert "self_edit" in p.deny_tools, f"{name}: builder must deny self_edit"
        assert cap.permits("self_edit") is False, f"{name}: self_edit reachable!"


def test_ops_compartments_are_sealed_by_tower():
    # Every Operations pack sits in an ops_* compartment (the Rung-2 seal boundary).
    for name, p in _OPS.items():
        assert p.compartment.startswith("ops_"), f"{name}: compartment={p.compartment!r}"


def test_suite_compartments_match_their_prefix():
    # A pack's compartment shares its suite prefix, so a Rung-2 seal quarantines the
    # whole suite/tower at once (the factory<->safety hinge).
    for pre, packs in (("itgrc_", _ITGRC), ("gtm_", _GTM), ("hr_", _HR),
                       ("strat_", _STRAT), ("pe_", _PE)):
        for name, p in packs.items():
            assert p.compartment.startswith(pre), f"{name}: compartment={p.compartment!r}"
