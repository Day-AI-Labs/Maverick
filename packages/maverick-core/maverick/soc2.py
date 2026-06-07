"""SOC 2 evidence collector — a machine-readable posture snapshot.

A SOC 2 audit (and any continuous-compliance automation in front of one) needs
to answer a simple question on demand: *which technical controls are actually
ON in this deployment right now, and is the tamper-evident audit log intact?*
This module answers it.

:func:`collect_soc2_evidence` returns a structured dict an auditor or a
``maverick soc2`` CLI command (a deliberate follow-on — see
``docs/compliance/soc2-controls.md``) can serialize to JSON and attach to an
evidence request. It probes the live configuration:

  - capability enforcement (``maverick.capability.capability_enforced``)
  - per-user tenant isolation (``maverick.paths.tenant_by_user_enabled``)
  - per-principal usage quotas (``maverick.quotas.quotas_enforced``)
  - OIDC auth verifier (``maverick.oidc.oidc_enabled``) — optional module
  - encryption at rest (``maverick.crypto_at_rest.at_rest_enabled``)
  - data-subject export / DSAR (``maverick.dsar.export_subject_data`` present)
  - the append-only Ed25519 Merkle-chained audit log: does it verify, and is a
    signing key present?

Design contract — this module is **fail-soft and import-light**:

  - It never raises. A probe that errors, or whose backing module is absent,
    is reported with ``status`` ``"unknown"`` (probe error) or ``"absent"``
    (module not installed) — never a crash. SOC 2 evidence collection must not
    be able to take down the host it is auditing. This explicitly includes
    ``BaseException``: a half-installed native crypto backend can ``panic`` (a
    pyo3 ``PanicException`` is a ``BaseException``, not an ``Exception``), and
    even that must degrade to ``"unknown"`` rather than abort the snapshot.
  - Every dependency is imported lazily inside the probe, so ``import
    maverick.soc2`` succeeds even when optional features (oidc/quotas) or
    ``cryptography`` are not installed.

The snapshot is descriptive, not prescriptive: ``"absent"``/``"unknown"`` are
honest states, not failures. The mapping of these controls to the SOC 2 Trust
Services Criteria lives in ``docs/compliance/soc2-controls.md``.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

# Status vocabulary for a single technical control probe.
#   enabled   — the control is configured ON in this deployment
#   disabled  — the control exists but is OFF (default-open / opt-in)
#   absent    — the backing module is not installed (optional feature)
#   unknown   — the probe raised; we caught it and refuse to crash
STATUS_ENABLED = "enabled"
STATUS_DISABLED = "disabled"
STATUS_ABSENT = "absent"
STATUS_UNKNOWN = "unknown"


def _probe_toggle(import_path: str, attr: str) -> dict[str, Any]:
    """Probe one boolean ``enabled()``-style control, fail-soft.

    ``import_path`` is a dotted module (e.g. ``"maverick.capability"``); ``attr``
    is a zero-arg predicate on it (e.g. ``"capability_enforced"``). Returns a
    small dict with a ``status`` from the vocabulary above and, when the call
    succeeded, the raw boolean under ``enabled``.

    Order of outcomes:
      - module missing              -> ``absent``
      - attr missing / not callable -> ``absent`` (treated as an unshipped
        feature, e.g. a future ``maverick.oidc`` that does not exist yet)
      - call raised                 -> ``unknown`` (with the error string)
      - call returned truthy/falsy  -> ``enabled`` / ``disabled``
    """
    import importlib

    try:
        module = importlib.import_module(import_path)
    except BaseException:  # noqa: BLE001 — fail-soft; absent OR unimportable
        # ImportError for a genuinely-absent optional module, but also any
        # error while importing it — either way the control is not usable here.
        return {"status": STATUS_ABSENT, "enabled": None}

    fn = getattr(module, attr, None)
    if not callable(fn):
        return {"status": STATUS_ABSENT, "enabled": None}

    try:
        value = bool(fn())
    except BaseException as exc:  # noqa: BLE001 — fail-soft; even a pyo3 panic
        # (PanicException is a BaseException) must not propagate out of a probe.
        return {"status": STATUS_UNKNOWN, "enabled": None, "error": str(exc)}

    return {
        "status": STATUS_ENABLED if value else STATUS_DISABLED,
        "enabled": value,
    }


def _probe_present(import_path: str, attr: str) -> dict[str, Any]:
    """Probe whether a *capability* (a callable) is shipped, fail-soft.

    Unlike :func:`_probe_toggle`, this reports the mere presence of an
    implemented feature rather than a runtime on/off toggle: it never calls
    ``attr``, only checks the module imports and the attribute is callable. Used
    for controls whose existence is the control (e.g. a DSAR export endpoint:
    GDPR Art. 15/20 access/portability is satisfied by the code being there).

    Order of outcomes (same fail-soft discipline as :func:`_probe_toggle`):
      - module missing / unimportable -> ``absent``
      - attr missing / not callable   -> ``absent`` (an unshipped feature)
      - both present                  -> ``enabled``

    Returns ``status`` from the shared vocabulary plus ``enabled`` (``True`` iff
    the capability is present). It never invokes the feature, so — unlike a
    toggle probe — there is no ``disabled``/``unknown`` outcome here.
    """
    import importlib

    try:
        module = importlib.import_module(import_path)
    except BaseException:  # noqa: BLE001 — fail-soft; absent OR unimportable
        return {"status": STATUS_ABSENT, "enabled": False}

    fn = getattr(module, attr, None)
    if not callable(fn):
        return {"status": STATUS_ABSENT, "enabled": False}

    return {"status": STATUS_ENABLED, "enabled": True}


def _safe(fn: Callable[[], Any], default: Any) -> Any:
    """Run ``fn`` and swallow anything it throws, returning ``default``.

    Catches ``BaseException`` on purpose: the audit probes call into the native
    crypto backend, which can ``panic`` (a pyo3 ``PanicException`` is a
    ``BaseException``) on a broken install. The fail-soft contract holds anyway.
    """
    try:
        return fn()
    except BaseException:  # noqa: BLE001 — see docstring; fail-soft is the point
        return default


def _resolve_audit_dir():
    """The active, tenant-scoped audit directory (``<data>/audit``).

    Mirrors :class:`maverick.audit.writer.AuditLog`'s own default so the snapshot
    reflects where rows are *currently* written — not a path a process singleton
    cached at import. Lazy import keeps this module light.
    """
    from .paths import data_dir

    return data_dir("audit")



def _probe_audit_chain() -> dict[str, Any]:
    """Verify the append-only Ed25519 Merkle-chained audit log, fail-soft.

    Resolves the active (tenant-aware) audit directory via :func:`_resolve_audit_dir`,
    then runs ``verify_chain`` over every day-file and ``verify_anchors`` over
    the cross-file anchor ledger. Reports one of:

      - ``ok``      — at least one day-file exists and all of them verify clean
      - ``broken``  — a day-file failed cryptographic verification: a real
        chain/hash/signature break (possible tampering). The count of breaks
        and the first reason are included.
      - ``unsigned`` — day-files exist but rows carry no hash/sig/key_id, i.e.
        audit signing is **off** (``[audit] sign`` / ``MAVERICK_AUDIT_SIGN``).
        The log is append-only NDJSON but not cryptographically tamper-evident.
        This is a *configuration* state, deliberately distinct from ``broken``
        so an auditor isn't alarmed by an un-enabled (not a tampered) chain.
      - ``empty``   — no day-files yet (a fresh deployment; not a failure)
      - ``no_crypto`` — ``cryptography`` is not installed, so the chain cannot
        be verified here (the log may still be signed elsewhere)
      - ``unknown`` — the probe itself errored; caught, never raised

    The cross-file anchor ledger (``anchors.ndjson``) is excluded from the
    per-day glob, then checked separately with ``verify_anchors`` so deletion or
    truncation of an entire completed day-file is still detected.
    """
    result: dict[str, Any] = {"status": STATUS_UNKNOWN}

    try:
        from .audit import verify_anchors, verify_chain
    except BaseException as exc:  # noqa: BLE001 — fail-soft import guard
        result["error"] = str(exc)
        return result

    # Resolve the active (tenant-aware) audit dir the same way the writer does —
    # via ``data_dir("audit")`` — rather than via the cached ``default_audit_log``
    # singleton, whose path is frozen at first construction and would be stale in
    # a long-lived / re-homed process (or under a different active tenant).
    audit_dir = _safe(lambda: _resolve_audit_dir(), None)
    if audit_dir is None:
        result["error"] = "could not resolve audit directory"
        return result
    result["audit_dir"] = str(audit_dir)

    day_files = _safe(
        lambda: sorted(
            p for p in audit_dir.glob("*.ndjson") if p.name != "anchors.ndjson"
        ),
        [],
    )
    real_breaks = 0  # genuine tamper/verify failures
    unsigned_rows = 0  # rows missing hash/sig/key_id (signing simply off)
    first_reason: str | None = None
    no_crypto = False
    for path in day_files:
        breaks = _safe(lambda p=path: verify_chain(p), None)
        if breaks is None:
            # verify_chain itself errored on this file — stay fail-soft and
            # surface it as unknown rather than silently claiming "ok".
            result["status"] = STATUS_UNKNOWN
            result["error"] = f"verify_chain raised for {path.name}"
            return result
        for b in breaks:
            reason = getattr(b, "reason", "")
            if reason == "no_crypto":
                no_crypto = True
                continue
            # An unsigned row (signing off) reports as a "malformed" break with
            # this exact detail; treat that as the benign "unsigned" state, not
            # tampering. Anything else is a real cryptographic break.
            if reason == "malformed" and "missing hash/sig/key_id" in (
                getattr(b, "detail", "") or ""
            ):
                unsigned_rows += 1
                continue
            real_breaks += 1
            if first_reason is None:
                first_reason = reason or "break"

    anchor_breaks = _safe(lambda: verify_anchors(audit_dir), None)
    if anchor_breaks is None:
        result["status"] = STATUS_UNKNOWN
        result["error"] = "verify_anchors raised"
        return result
    for b in anchor_breaks:
        reason = getattr(b, "reason", "")
        if reason == "no_crypto":
            no_crypto = True
            continue
        # A missing anchor ledger for completed day-files is always a real
        # integrity break. Do not downgrade it based on current signing config
        # or key presence: those signals can be unavailable after tampering, and
        # suppressing this break lets stripped signed history look unsigned.
        real_breaks += 1
        if first_reason is None:
            first_reason = reason or "anchor_break"

    result["files_checked"] = len(day_files)
    result["anchors_checked"] = True
    if real_breaks:
        result["status"] = "broken"
        result["breaks"] = real_breaks
        result["first_reason"] = first_reason
        return result
    if no_crypto:
        result["status"] = "no_crypto"
        return result
    if not day_files:
        result["status"] = "empty"
        return result
    if unsigned_rows:
        result["status"] = "unsigned"
        result["unsigned_rows"] = unsigned_rows
        return result
    result["status"] = "ok"
    return result


def _probe_signing_key() -> dict[str, Any]:
    """Report whether an audit signing key (the chain's trust anchor) is present.

    A present private ``.key`` means this host can sign new audit rows; without
    it the log is append-only NDJSON but not cryptographically tamper-evident.
    Fail-soft: any error -> ``status`` ``unknown``.
    """
    result: dict[str, Any] = {"status": STATUS_UNKNOWN}
    try:
        from .audit import signing
    except BaseException as exc:  # noqa: BLE001 — fail-soft import guard
        result["error"] = str(exc)
        return result

    key_dir = _safe(signing._key_dir, None)
    if key_dir is None:
        result["error"] = "could not resolve key directory"
        return result
    result["key_dir"] = str(key_dir)

    keys = _safe(lambda: sorted(p.name for p in key_dir.glob("*.key")), None)
    if keys is None:
        result["error"] = "could not enumerate key directory"
        return result
    result["present"] = bool(keys)
    result["key_count"] = len(keys)
    result["status"] = STATUS_ENABLED if keys else STATUS_ABSENT
    return result


def _maverick_version() -> str:
    return _safe(lambda: __import__("maverick").__version__, "unknown")


def collect_soc2_evidence() -> dict[str, Any]:
    """Return a structured SOC 2 posture snapshot for an auditor/automation.

    The returned dict is JSON-serializable and stable in shape (top-level keys
    are always present even when a probe is ``absent``/``unknown``):

      - ``version``      — maverick package version (str; ``"unknown"`` on error)
      - ``collected_at`` — UTC epoch seconds when the snapshot was taken (float)
      - ``controls``     — per-control technical-toggle probes, keyed by a short
        control id; each value has a ``status`` and (for toggles) ``enabled``:
          * ``capability_enforcement`` — signed attenuating per-agent grants
          * ``tenant_isolation``       — per-user multi-tenant data isolation
          * ``usage_quotas``           — per-principal daily spend/token caps
          * ``oidc_auth``              — OIDC ID-token verifier (optional module)
          * ``encryption_at_rest``     — AES-256-GCM at-rest encryption toggle
          * ``data_subject_export``    — DSAR access/portability export present
            (a presence probe: ``enabled``/``absent``, never a runtime toggle)
      - ``audit_log``    — audit-chain verification: ``ok`` / ``broken`` /
        ``unsigned`` / ``empty`` / ``no_crypto`` / ``unknown`` (see
        ``_probe_audit_chain``)
      - ``audit_signing_key`` — signing-key presence (see ``_probe_signing_key``)

    Never raises. Probe a deployment with confidence: a missing optional module
    is reported as ``absent`` and a probe that throws as ``unknown`` — the call
    always returns a dict.
    """
    return {
        "version": _maverick_version(),
        "collected_at": time.time(),
        "controls": {
            "capability_enforcement": _probe_toggle(
                "maverick.capability", "capability_enforced"
            ),
            "tenant_isolation": _probe_toggle(
                "maverick.paths", "tenant_by_user_enabled"
            ),
            "usage_quotas": _probe_toggle("maverick.quotas", "quotas_enforced"),
            "oidc_auth": _probe_toggle("maverick.oidc", "oidc_enabled"),
            "encryption_at_rest": _probe_toggle(
                "maverick.crypto_at_rest", "at_rest_enabled"
            ),
            "data_subject_export": _probe_present(
                "maverick.dsar", "export_subject_data"
            ),
        },
        "audit_log": _safe(_probe_audit_chain, {"status": STATUS_UNKNOWN}),
        "audit_signing_key": _safe(_probe_signing_key, {"status": STATUS_UNKNOWN}),
    }


__all__ = ["collect_soc2_evidence"]
