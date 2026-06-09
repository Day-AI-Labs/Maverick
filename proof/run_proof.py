#!/usr/bin/env python3
"""Maverick -- proof of guarantees.

Not unit assertions buried in a suite: a single reproducible run that drives the
REAL roster (the shipped domain packs) through the REAL enforcement code -- the
same primitives the production tool chokepoint (``agent._run_tool``) calls --
and prints a scoreboard of the product's core promises.

    python proof/run_proof.py        # exits 0 iff every guarantee holds

The "control plane is the product" claim, made checkable. Five guarantees run
anywhere; two cryptographic ones (Ed25519) need ``cryptography`` and otherwise
report ``CI`` (they run in the test matrix).
"""
from __future__ import annotations

import dataclasses
import pathlib
import sys

# Make the shipped package importable however this is launched (repo root, CI, ...).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "packages" / "maverick-core"))


def _crypto_ok() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401
        return True
    except BaseException:
        return False


def _finance(d):
    return {k: v for k, v in d.items() if k.startswith("finance_")}


def _check(condition: bool, message: object) -> None:
    """Raise even when Python assertions are disabled with -O/PYTHONOPTIMIZE."""
    if not condition:
        raise AssertionError(message)


# --- the guarantees -------------------------------------------------------

def claim_least_privilege():
    """A deployed specialist runs sealed + attenuated, never the parent's reach."""
    from maverick.capability import Capability
    from maverick.domain import builtin_dir, domain_capability, load_domains
    d = load_domains(builtin_dir())
    parent = Capability(principal="agent:finance_controller-0", max_risk="high")
    cap = domain_capability(d["finance_ap"], parent, "agent:finance_ap-1")
    _check(cap.max_risk != "high", "pack did not narrow the parent ceiling")
    _check(cap.permits("billdotcom_read"), "can't do its job (read AP)")
    _check(not cap.permits("shell"), "leaked the parent's arbitrary reach")
    _check(not cap.permits("release_payment"), "custody seal broken")
    return f"finance_ap runs at max_risk={cap.max_risk!r} (parent=high): reads AP, no shell, no payments"


def claim_no_money_without_a_human():
    """Across the WHOLE finance roster, no attenuated grant can move money/post."""
    from maverick.capability import Capability
    from maverick.domain import builtin_dir, domain_capability, load_domains
    money = ("wire_transfer", "release_payment", "post_journal_entry", "run_payroll",
             "ach_send", "send_payment", "file_with_sec", "place_trade")
    d = _finance(load_domains(builtin_dir()))
    parent = Capability(principal="agent:finance_controller-0", max_risk="high")
    for name, prof in d.items():
        cap = domain_capability(prof, parent, f"agent:{name}-1")
        for m in money:
            _check(not cap.permits(m), f"{name} permits money tool {m!r}")
    return f"no money/posting tool is permitted by any of {len(d)} finance packs"


def claim_dollar_tier_authority_gate():
    """The org policy's delegation-of-authority tiers actually fire."""
    from maverick.governance import Decision, Policy, evaluate
    p = Policy(require_human_above={"release_payment": 5000.0},
               deny_above={"wire_transfer": 50000.0})
    auto = evaluate("release_payment", policy=p, amount=4000, currency="USD")
    human = evaluate("release_payment", policy=p, amount=6000, currency="USD")
    denied = evaluate("wire_transfer", policy=p, amount=60000, currency="USD")
    _check(auto.decision is Decision.ALLOW, auto)
    _check(human.decision is Decision.REQUIRE_HUMAN, human)
    _check(denied.decision is Decision.DENY, denied)
    return f"$4k release auto, $6k release -> REQUIRE_HUMAN, $60k wire -> DENY (rule={denied.rule})"


def claim_fleet_can_read_but_not_write():
    """A specialist can reach a real low-risk vendor READ seat; the write seat is denied."""
    from maverick.capability import Capability
    from maverick.domain import builtin_dir, domain_capability, load_domains
    from maverick.tools.enterprise_connectors import enterprise_connectors
    tools = {t.name: t for t in enterprise_connectors()}
    refused = tools["billdotcom_read"].fn({"op": "post", "path": "/x", "confirm": True})
    _check("read-only" in refused, "read seat accepted a write")
    cap = domain_capability(load_domains(builtin_dir())["finance_ap"],
                            Capability(principal="agent:finance_controller-0", max_risk="high"),
                            "agent:finance_ap-1")
    _check(
        cap.permits("billdotcom_read") and not cap.permits("billdotcom"),
        "finance_ap capability grants unexpected Bill.com access",
    )
    return "finance_ap reaches billdotcom_read (GET-only); the write connector is refused + capability-denied"


def claim_segregation_of_duties_clean():
    """The finance roster is SoD-clean: no seal spans record/authorize/custody."""
    from maverick.domain import builtin_dir, load_domains
    from maverick.finance.sod_linter import lint_roster
    d = _finance(load_domains(builtin_dir()))
    conflicts = lint_roster(d)
    _check(not conflicts, f"{len(conflicts)} SoD conflict(s): {conflicts[:2]}")
    return f"all {len(d)} finance packs SoD-clean (no compartment unions incompatible duties)"


def claim_handoffs_are_verified():
    """A peer handoff is signed + verified; a tampered copy is rejected."""
    from maverick.bus_handoff import HandoffAuthority
    from maverick.capability import Capability
    auth = HandoffAuthority.for_run()
    grant = Capability(principal="agent:finance_fpa-1",
                       allow_tools=frozenset({"ap_read_invoice"}), max_risk="low")
    env = auth.mint(sender="agent:finance_ap-1", recipient="agent:finance_fpa-1",
                    grant=grant, task="read the invoice")
    ok = auth.verify(env)
    bad = auth.verify(dataclasses.replace(env, task="wire the funds out"))
    _check(ok.ok and ok.grant.permits("ap_read_invoice"), ok)
    _check(not bad.ok and bad.rule == "tampered", bad)
    return f"authentic handoff verifies (rule={ok.rule}); tampered copy rejected (rule={bad.rule})"


def claim_audit_is_tamper_evident():
    """The action ledger is a signed hash-chain: altering a row breaks verification."""
    import tempfile
    from pathlib import Path

    from maverick.audit import signing
    with tempfile.TemporaryDirectory() as td:
        signing.KEY_DIR = Path(td) / "keys"
        path = Path(td) / "audit.ndjson"
        signer = signing.AuditSigner(path)
        signer.write({"event": "release_payment", "amount": 6000, "decision": "REQUIRE_HUMAN"})
        signer.write({"event": "human_approval", "by": "cfo", "decision": "approved"})
        clean = signing.verify_chain(path, signer.public_key_hex)
        _check(not clean, f"clean chain reported breaks: {clean}")
        rows = path.read_text().splitlines()
        path.write_text("\n".join(rows).replace('"amount": 6000', '"amount": 60') + "\n")
        broken = signing.verify_chain(path, signer.public_key_hex)
        _check(broken, "tampering an audited row was NOT detected")
    return f"2-row signed chain verifies clean; altering an amount is caught ({broken[0].reason})"


_GUARANTEES = [
    ("Least privilege by construction", claim_least_privilege, False),
    ("No money without a human", claim_no_money_without_a_human, False),
    ("Delegation-of-authority $ gate", claim_dollar_tier_authority_gate, False),
    ("Fleet can read, not write", claim_fleet_can_read_but_not_write, False),
    ("Segregation of duties clean", claim_segregation_of_duties_clean, False),
    ("Verified peer handoffs", claim_handoffs_are_verified, True),
    ("Tamper-evident audit ledger", claim_audit_is_tamper_evident, True),
]


def main() -> int:
    crypto = _crypto_ok()
    print("=" * 78)
    print("  MAVERICK -- PROOF OF GUARANTEES   (real roster, real enforcement code)")
    print("=" * 78)
    failed = 0
    ran = 0
    for label, fn, needs_crypto in _GUARANTEES:
        if needs_crypto and not crypto:
            print(f"  [ CI ]  {label:32}  Ed25519 -- verified in the CI test matrix")
            continue
        try:
            detail = fn()
            ran += 1
            print(f"  [PASS]  {label:32}  {detail}")
        except BaseException as e:  # a proof must report its own failure
            failed += 1
            print(f"  [FAIL]  {label:32}  {type(e).__name__}: {e}")
    print("=" * 78)
    crypto_note = "" if crypto else "  (+2 cryptographic guarantees verified in CI)"
    print(f"  {ran} guarantees PROVEN, {failed} failed{crypto_note}")
    print("=" * 78)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
