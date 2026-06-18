"""Regulated-deployment profile + a live verifier for the data-boundary guarantees.

Enterprise mode, at-rest encryption, audit signing and retention each turn on a
piece of the "safe to run on private / sensitive data" posture. This module ties
them into ONE named profile (:data:`REGULATED_PROFILE`) and a verifier that
*actively exercises* the load-bearing guarantees -- it does not merely read the
config flags the way ``maverick compliance`` does. It proves the egress lock
refuses a cloud provider and that at-rest sealing actually round-trips on this
box, which is the difference between "the flag is on" and "the boundary holds"
(a flag can read ``active`` while the ``cryptography`` backend or the key is in
fact missing, which would only surface as a fail-closed error at write time).

Surfaced as ``maverick enterprise verify``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

# The one reference profile. Enabling these together makes
# ``maverick compliance --strict`` green and the verifier below pass. Enterprise
# mode alone covers egress lock + fail-closed consent + capability enforcement +
# at-rest encryption; signing and retention are the two extra knobs. Kept here so
# docs/regulated-deployment.md and the code never drift.
REGULATED_PROFILE = """\
[enterprise]
mode = true            # egress lock + fail-closed consent + capabilities + at-rest encryption

[audit]
sign = true            # Ed25519 tamper-evident audit chain

[retention]
audit_days = 365       # storage limitation (GDPR Art. 5(1)(e)) -- tune to your policy
episodes_days = 90
events_days = 365
"""

# Representative providers used to prove the egress policy without contacting
# either: a known cloud provider must be refused, a self-hosted one admitted.
_CLOUD_PROBE = "anthropic"
_LOCAL_PROBE = "ollama"
_SEAL_PROBE = "maverick-at-rest-probe"


@dataclass(frozen=True)
class GuaranteeCheck:
    """One data-boundary guarantee and whether it currently holds."""

    name: str
    passed: bool
    detail: str


def verify_deployment() -> list[GuaranteeCheck]:
    """Actively verify the regulated-deployment guarantees on this box.

    Unlike :func:`maverick.compliance.compliance_report` (which maps configured
    controls to regulation articles), this exercises the load-bearing ones so a
    pass means the boundary actually holds, not just that a flag is set.
    """
    checks: list[GuaranteeCheck] = []

    # 1. Egress lock -- prove the policy refuses a cloud provider and admits a
    #    self-hosted one, using the same predicates the LLM chokepoint enforces.
    #    No network call and no audit side effect, so it is idempotent / CI-safe.
    from .enterprise import enterprise_enabled, is_local_provider
    ent = enterprise_enabled()
    cloud_blocked = ent and not is_local_provider(_CLOUD_PROBE)
    local_ok = is_local_provider(_LOCAL_PROBE)
    checks.append(GuaranteeCheck(
        "Egress lock",
        bool(cloud_blocked and local_ok),
        f"enterprise mode on; cloud provider {_CLOUD_PROBE!r} refused, self-hosted "
        f"{_LOCAL_PROBE!r} allowed (guard raises EgressBlocked at the LLM chokepoint)"
        if cloud_blocked and local_ok
        else "enable [enterprise] mode = true -- data can currently reach a cloud API",
    ))

    # 2. At-rest encryption -- actually seal + unseal a probe so a missing crypto
    #    backend or unreadable key fails here instead of silently at write time.
    from .crypto_at_rest import EncryptionUnavailable, at_rest_enabled
    enc_ok = False
    enc_detail = "enable [encryption] at_rest = true (or enterprise mode) to seal data"
    if at_rest_enabled():
        try:
            from .crypto_at_rest import seal_to_str, unseal_from_str
            sealed = seal_to_str(_SEAL_PROBE)
            enc_ok = (
                sealed != _SEAL_PROBE
                and _SEAL_PROBE not in sealed
                and unseal_from_str(sealed) == _SEAL_PROBE
            )
            enc_detail = (
                "AES-256-GCM seal/unseal round-trips; plaintext absent from ciphertext"
                if enc_ok
                else "at-rest encryption enabled but seal/unseal failed"
            )
        except EncryptionUnavailable as e:
            enc_detail = f"at-rest enabled but unavailable: {e}"
    checks.append(GuaranteeCheck("At-rest encryption", enc_ok, enc_detail))

    # 3. Tamper-evident audit -- exercise the same signer/key path real audit
    #    writes depend on.  Import-only crypto checks can pass while a malformed
    #    or unreadable key makes the writer fall back to unsigned rows, so append
    #    and verify a signed probe chain.
    checks.append(_verify_audit_signing())

    # 4. Human oversight -- destructive actions are consent-gated, not auto-approved.
    mode = "auto-approve"
    try:
        from .safety.consent import _resolve_mode
        mode = _resolve_mode()
    except Exception:
        pass
    oversight = mode in {"ask", "dashboard", "auto-deny"}
    checks.append(GuaranteeCheck(
        "Human oversight",
        oversight,
        f"consent mode = {mode}" if oversight
        else "set MAVERICK_CONSENT_MODE=ask (or enable enterprise mode)",
    ))

    # 5. Retention -- storage limitation configured (GDPR Art. 5(1)(e)).
    retention = False
    try:
        from .config import load_config
        retention = bool((load_config() or {}).get("retention"))
    except Exception:
        pass
    checks.append(GuaranteeCheck(
        "Retention policy",
        retention,
        "configured; enforce with 'maverick retention enforce'" if retention
        else "set [retention] audit_days / episodes_days / events_days",
    ))

    # 6. Sandbox isolation -- agent-generated code must not run unsandboxed on
    # the host. The 'local' backend executes shell=True with no isolation.
    backend = "local"
    try:
        from .config import load_config
        backend = str(
            (load_config() or {}).get("sandbox", {}).get("backend") or "local"
        ).strip().lower()
    except Exception:
        pass
    sandboxed = backend not in ("", "local")
    checks.append(GuaranteeCheck(
        "Sandbox isolation",
        sandboxed,
        f"backend = {backend}" if sandboxed
        else "set [sandbox] backend = \"docker\" (or podman/gvisor/kubernetes/"
             "firecracker); 'local' runs agent code on the host unsandboxed",
    ))

    return checks


def _verify_audit_signing() -> GuaranteeCheck:
    """Write and verify a signed probe using the real audit signing key path."""
    name = "Tamper-evident audit"
    detail = "enable [audit] sign = true (or MAVERICK_AUDIT_SIGN=1)"
    probe = None
    try:
        from .audit.writer import _resolve_signing

        if not _resolve_signing(None):
            return GuaranteeCheck(name, False, detail)

        from .audit.signing import AuditSigner, _have_crypto, verify_chain

        if not _have_crypto():
            return GuaranteeCheck(
                name,
                False,
                "audit signing requested but 'cryptography' is not installed",
            )

        from .paths import data_dir

        audit_dir = data_dir("audit")
        audit_dir.mkdir(parents=True, exist_ok=True)
        probe = audit_dir / ".enterprise-verify-probe.ndjson"
        try:
            probe.unlink()
        except FileNotFoundError:
            pass

        signer = AuditSigner(probe)
        wrote = signer.write({
            "kind": "enterprise_verify_probe",
            "agent": "system",
            "goal_id": None,
            "v": 1,
        })
        breaks = verify_chain(probe) if wrote else []
        passed = bool(wrote and not breaks)
        detail = (
            "Ed25519 hash-chain probe wrote and verified; verify logs with "
            "'maverick audit verify'"
            if passed
            else "audit signing probe failed to write or verify"
        )
        return GuaranteeCheck(name, passed, detail)
    except Exception as e:
        return GuaranteeCheck(name, False, f"audit signing probe failed: {e}")
    finally:
        try:
            if probe is not None:
                probe.unlink()
        except Exception:
            pass


def all_passed(checks: list[GuaranteeCheck]) -> bool:
    return all(c.passed for c in checks)


def render_text(checks: list[GuaranteeCheck]) -> str:
    head = "Regulated-deployment guarantees"
    width = max((len(c.name) for c in checks), default=10)
    lines = [head, "=" * len(head), ""]
    for c in checks:
        lines.append(f"  [{'PASS' if c.passed else 'FAIL'}]  {c.name:<{width}}  {c.detail}")
    passed = sum(1 for c in checks if c.passed)
    lines += ["", f"{passed}/{len(checks)} guarantees hold"]
    if not all_passed(checks):
        lines += [
            "",
            "Not deployment-ready. Apply the regulated profile "
            "(docs/regulated-deployment.md) and re-run.",
        ]
    return "\n".join(lines)


def render_json(checks: list[GuaranteeCheck]) -> str:
    import json
    return json.dumps(
        {
            "guarantees": [asdict(c) for c in checks],
            "all_passed": all_passed(checks),
        },
        indent=2,
    )


__all__ = [
    "REGULATED_PROFILE",
    "GuaranteeCheck",
    "verify_deployment",
    "all_passed",
    "render_text",
    "render_json",
]
