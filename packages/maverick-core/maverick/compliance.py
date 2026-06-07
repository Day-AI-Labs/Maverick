"""EU AI Act Article 50 transparency disclosure for channel users.

The EU AI Act becomes enforceable Aug 2 2026 — see May 2026 Commission
guidelines covering agentic AI as a single high-risk system. Article 50
mandates that users interacting with a chatbot must be informed they
are talking to AI unless that fact is obvious from context.

This module gives the channel server a single function:

    disclosure = first_turn_disclosure(channel, user_id)

It returns the disclosure string to PREPEND to the agent's first reply
on each new conversation, or None if the user has already seen it (we
track via the world model's conversations.last_seen vs created_at).
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass

# Default text. Can be overridden via:
#   MAVERICK_AI_DISCLOSURE="<your custom text>"
# or [compliance] disclosure_text in ~/.maverick/config.toml.
DEFAULT_DISCLOSURE = (
    "Hi -- I'm Maverick, an AI assistant. Conversations may be reviewed "
    "for safety. Reply STOP to end."
)


_UNSET = object()


def _custom_disclosure():
    """Return a 3-state result:
      - explicit non-empty string  -> use it
      - explicit empty string      -> opt-out (return "")
      - not configured at all      -> _UNSET (caller uses default)
    """
    env = os.environ.get("MAVERICK_AI_DISCLOSURE")
    if env is not None:
        return env
    try:
        from .config import load_config
        text = load_config().get("compliance", {}).get("disclosure_text")
        if text is not None:
            return text
    except Exception:
        pass
    return _UNSET


def first_turn_disclosure(
    world,
    channel: str,
    user_id: str,
) -> str | None:
    """Return the AI disclosure string for the user's first turn, or None.

    "First turn" = no prior conversation row OR the conversation has
    zero assistant turns yet. Subsequent turns on the same conversation
    return None so we don't spam the user. Per Article 50 the user
    must be informed at the start of the interaction.

    The conversation row is created/updated as a side effect to keep
    this idempotent across retries.
    """
    conv = world.get_or_create_conversation(channel=channel, user_id=user_id)
    # If any prior assistant turn exists, the user has already seen
    # the disclosure (or the operator opted out via empty text). Skip.
    prior = world.recent_turns(conv.id, limit=1)
    for t in prior:
        if t.role == "assistant":
            return None
    text = _custom_disclosure()
    if text is _UNSET:
        text = DEFAULT_DISCLOSURE
    if not text or not text.strip():
        # Operator explicitly opted out (empty string). Don't disclose.
        return None
    return text


# ---------------------------------------------------------------------------
# Compliance posture report
#
# Honest framing (the liability line): this reports *control coverage*, not a
# legal compliance attestation. Full GDPR / EU AI Act compliance also requires
# organizational + legal measures the code cannot perform (DPA, ROPA/Art. 30
# records, DPIA, risk classification, and review by qualified counsel).
# ---------------------------------------------------------------------------

COMPLIANCE_DISCLAIMER = (
    "Control-coverage report, not legal advice or a compliance attestation. "
    "Full GDPR / EU AI Act compliance also requires organizational and legal "
    "measures (DPA, ROPA/Art. 30 records, DPIA, AI-Act risk classification, and "
    "review by qualified counsel)."
)


@dataclass(frozen=True)
class ControlCheck:
    """One control mapped to the regulation article(s) it supports.

    ``status`` is one of:
      - ``active``        — enforced right now for this deployment.
      - ``available``     — a feature/command exists, invoked on demand.
      - ``action_needed`` — an opt-in control that is currently off.
    """

    control: str
    regulation: str
    status: str
    detail: str


def _report_cfg() -> dict:
    try:
        from .config import load_config
        return load_config() or {}
    except Exception:
        return {}


def compliance_report() -> list[ControlCheck]:
    """Introspect this deployment and map active controls to GDPR + EU AI Act
    articles. The result powers ``maverick compliance``."""
    cfg = _report_cfg()
    checks: list[ControlCheck] = []

    # EU AI Act Art. 50 — transparency disclosure (wired into the channel server).
    disclosure = _custom_disclosure()
    art50_on = disclosure is _UNSET or bool(disclosure and str(disclosure).strip())
    checks.append(ControlCheck(
        "AI transparency disclosure", "EU AI Act Art. 50",
        "active" if art50_on else "action_needed",
        "first-turn AI disclosure shown to channel users" if art50_on
        else "re-enable by unsetting [compliance] disclosure_text (empty = disabled)",
    ))

    # EU AI Act Art. 12 / GDPR Art. 30 — record-keeping.
    checks.append(ControlCheck(
        "Audit logging (record-keeping)", "EU AI Act Art. 12 / GDPR Art. 30",
        "active", "append-only event log at ~/.maverick/audit/YYYY-MM-DD.ndjson",
    ))
    signing_requested = False
    signing_available = False
    try:
        from .audit.writer import _resolve_signing

        signing_requested = bool(_resolve_signing(None))
        if signing_requested:
            from .audit.signing import _have_crypto

            signing_available = _have_crypto()
    except Exception:
        signing_available = False
    signing_on = signing_requested and signing_available
    if signing_on:
        signing_detail = "Ed25519 hash-chain on; verify with 'maverick audit verify'"
    elif signing_requested:
        signing_detail = (
            "install audit signing support with "
            "pip install 'maverick-agent[audit-signing]'"
        )
    else:
        signing_detail = "enable [audit] sign = true (or MAVERICK_AUDIT_SIGN=1)"
    checks.append(ControlCheck(
        "Tamper-evident audit", "EU AI Act Art. 12",
        "active" if signing_on else "action_needed",
        signing_detail,
    ))

    # EU AI Act Art. 14 — human oversight.
    mode = "auto-approve"
    try:
        from .safety.consent import _resolve_mode
        mode = _resolve_mode()
    except Exception:
        pass
    oversight_on = mode in {"ask", "dashboard", "auto-deny"}
    checks.append(ControlCheck(
        "Human oversight (consent gating)", "EU AI Act Art. 14",
        "active" if oversight_on else "action_needed",
        f"consent mode = {mode}" if oversight_on
        else "set MAVERICK_CONSENT_MODE=ask/dashboard, or enable enterprise mode",
    ))
    checks.append(ControlCheck(
        "Kill switch", "EU AI Act Art. 14", "available",
        "create ~/.maverick/HALT to abort all running goals",
    ))

    # GDPR Art. 15 & 20 — access + portability.
    checks.append(ControlCheck(
        "Data-subject access & portability", "GDPR Art. 15 & 20", "available",
        "maverick export-user --channel <c> --user <u>",
    ))
    # GDPR Art. 17 — erasure.
    checks.append(ControlCheck(
        "Right to erasure", "GDPR Art. 17", "available",
        "maverick erase --channel <c> --user <u> (re-anchors the signed audit)",
    ))

    # GDPR Art. 5(1)(e) — storage limitation / retention.
    retention_on = bool(cfg.get("retention"))
    checks.append(ControlCheck(
        "Storage limitation (retention)", "GDPR Art. 5(1)(e)",
        "active" if retention_on else "action_needed",
        "retention configured; run 'maverick retention enforce'" if retention_on
        else "set [retention] audit_days / episodes_days / events_days",
    ))

    # GDPR Art. 32 / EU AI Act Art. 15 — security: data egress.
    ent_on = False
    try:
        from .enterprise import enterprise_enabled
        ent_on = enterprise_enabled()
    except Exception:
        pass
    checks.append(ControlCheck(
        "Data-egress control", "GDPR Art. 32 / EU AI Act Art. 15",
        "active" if ent_on else "action_needed",
        "enterprise mode: LLM calls pinned to local/self-hosted providers" if ent_on
        else "enable [enterprise] mode = true to keep data on-box",
    ))

    # GDPR Art. 25 & 32 — data protection by design (redaction always on in audit).
    checks.append(ControlCheck(
        "Secret/PII redaction in logs", "GDPR Art. 25 & 32", "active",
        "audit events pass through the secret detector before write",
    ))

    # GDPR Art. 32 — encryption of personal data at rest (memory store).
    enc_on = False
    try:
        from .crypto_at_rest import at_rest_enabled
        enc_on = at_rest_enabled()
    except Exception:
        pass
    checks.append(ControlCheck(
        "Encryption at rest", "GDPR Art. 32",
        "active" if enc_on else "action_needed",
        "AES-256-GCM seals the memory store + world-DB conversation turns & facts"
        if enc_on
        else "enable [encryption] at_rest = true (or enterprise mode) to seal it",
    ))

    anon_on = False
    try:
        from .privacy import anon_enabled
        anon_on = anon_enabled()
    except Exception:
        pass
    checks.append(ControlCheck(
        "Log data minimization (anonymous mode)", "GDPR Art. 5(1)(c)",
        "active" if anon_on else "available",
        "anonymous mode on" if anon_on
        else "enable [privacy] anonymous = true to hash identifiers in logs",
    ))

    return checks


_STATUS_LABEL = {
    "active": "active",
    "available": "on-demand",
    "action_needed": "ACTION NEEDED",
}


def render_report_text(checks: list[ControlCheck]) -> str:
    width = max((len(c.control) for c in checks), default=10)
    rows: list[str] = []
    for c in checks:
        rows.append(f"  [{_STATUS_LABEL.get(c.status, c.status):>13}]  {c.control:<{width}}  {c.regulation}")
        rows.append(f"  {'':>13}    {'':<{width}}  -> {c.detail}")
    active = sum(1 for c in checks if c.status == "active")
    needed = sum(1 for c in checks if c.status == "action_needed")
    head = "GDPR + EU AI Act — control coverage"
    return "\n".join([
        head, "=" * len(head), "", *rows, "",
        f"{active} active, {needed} need action, {len(checks)} total", "",
        COMPLIANCE_DISCLAIMER,
    ])


def render_report_json(checks: list[ControlCheck]) -> str:
    import json
    return json.dumps(
        {
            "controls": [asdict(c) for c in checks],
            "summary": {
                "active": sum(1 for c in checks if c.status == "active"),
                "action_needed": sum(1 for c in checks if c.status == "action_needed"),
                "total": len(checks),
            },
            "disclaimer": COMPLIANCE_DISCLAIMER,
        },
        indent=2,
    )
