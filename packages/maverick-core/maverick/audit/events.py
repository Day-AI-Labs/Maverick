"""Audit event schema. Versioned, additive-only.

To add a new event kind:
  1. Add it to ``EventKind`` here.
  2. Bump ``SCHEMA_VERSION`` if the payload shape changes for an
     EXISTING kind (new kinds are additive — no bump needed).
  3. Document the payload shape in this file's module docstring.

Payload shapes (kind -> required fields, all events also carry
``ts``, ``goal_id``, ``agent``, ``kind``):

  goal_start:        title:str, description:str|None
  goal_end:          status:str (succeeded|failed|cancelled), result:str|None
  episode_start:     attempt:int, model:str
  episode_end:       outcome:str, cost_dollars:float, in_tok:int, out_tok:int
  tool_call:         name:str, input_summary:str (truncated)
  tool_result:       name:str, status:str, output_summary:str
  shield_block:      stage:str (input|tool|output), reason:str, score:float|None
  capability_denied: tool:str, principal:str, channel:str|None, user_id:str|None
  egress_blocked:    provider:str (enterprise-mode egress lock denial)
  consent_prompt:    action:str, risk:str (low|medium|high|critical)
  consent_result:    decision:str (approve|deny|timeout)
  secret_redacted:   tool_name:str, pattern:str, count:int
  erase:             channel:str, erasure_id:str (random token, never subject-derived)
  halt:              source:str (file|signal|manual), detail:str|None
  federation_delegate: peer_node:str (absent when the caller was unauthenticated),
                     correlation_id:str, direction:str (sent|received),
                     accepted:bool, reason:str ("" when accepted) — one half of a
                     cross-swarm delegation; reciprocity of the two halves is
                     verified by ``audit/federation.cross_verify``
  agent_trust_denied: peer:str, direction:str (inbound|outbound), rule:str,
                     reason:str, correlation_id:str — an external agent was
                     refused by the Agent Trust Plane.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_valid_day(day: Any) -> bool:
    """True iff ``day`` is a real ``YYYY-MM-DD`` calendar date.

    An audit ``day`` becomes a filesystem path component
    (``<audit_dir>/<day>.ndjson``), so anything that isn't this exact shape
    -- ``..``, a path separator, an absolute path, a NUL -- could escape the
    audit dir. The anchored shape check is the path-safety gate; on top of it
    we require a genuine calendar date, so a typo'd ``--day`` (``2026-13-99``,
    ``2026-02-30``) is a friendly error instead of a misleading "no entries /
    OK" on a day-file that could never exist (UX finding). Every code path that
    builds a day-file path from an untrusted ``day`` must gate on this first.
    (Mirrors the dashboard's own ``safe_audit_day`` HTTP-boundary guard.)
    """
    if not (isinstance(day, str) and _DAY_RE.match(day)):
        return False
    import datetime
    try:
        datetime.date.fromisoformat(day)
    except ValueError:
        return False
    return True


class EventKind:
    """Stringly-typed event kinds. Use these constants, not bare strings."""
    GOAL_START      = "goal_start"
    GOAL_END        = "goal_end"
    EPISODE_START   = "episode_start"
    EPISODE_END     = "episode_end"
    TOOL_CALL       = "tool_call"
    TOOL_RESULT     = "tool_result"
    SHIELD_BLOCK    = "shield_block"
    CAPABILITY_DENIED = "capability_denied"
    # Per-call token exchange (zero-trust): one row per minted, single-tool,
    # short-lived capability token, so the Operating Record shows the scoped
    # credential each tool call actually ran under -- not just the run-long grant.
    TOKEN_EXCHANGE = "token_exchange"
    GOVERNANCE_DENIED = "governance_denied"
    AUTONOMY_ESCALATED = "autonomy_escalated"
    AUTONOMY_GATED = "autonomy_gated"
    EGRESS_BLOCKED  = "egress_blocked"
    CONSENT_PROMPT  = "consent_prompt"
    CONSENT_RESULT  = "consent_result"
    SECRET_REDACTED = "secret_redacted"
    ERASE           = "erase"
    HALT            = "halt"
    CONFIG_REMEDIATED = "config_remediated"
    FEDERATION_DELEGATE = "federation_delegate"
    # Agent Trust Plane: an external agent was refused an inbound action or an
    # outbound dial because it is absent from the [agent_trust] registry, its
    # direction forbade the interaction, or it exceeded its tool/risk ceiling.
    # payload: peer:str, direction:str (inbound|outbound), rule:str, reason:str,
    # correlation_id:str ("" when none).
    AGENT_TRUST_DENIED = "agent_trust_denied"
    # Learning governance: one row per dream cycle (what the learning system
    # wrote/retired/quarantined) so `maverick audit verify` covers learned
    # state the same way it covers tool calls.
    LEARNING_UPDATE = "learning_update"
    # Memory governance (OWASP ASI06): a memory write was stamped/screened, or a
    # trust-aware retrieval pass filtered low-trust memory out of the brief.
    # payload: action:str (write|write_blocked|recall_filter), plus key/source/
    # trust/sensitivity/reason/markers (writes) or kept/dropped/min_trust (recall).
    MEMORY_GUARD = "memory_guard"
    # Tamper-evident before/after capture for a governed computer/browser action.
    # payload: action:str (e.g. "browser.click"), phase:str (before|after),
    # file:str (capture basename under data_dir("captures")), sha256:str (sealed
    # digest, verifiable via screenshot_seal.verify_file).
    EVIDENCE_CAPTURE = "evidence_capture"


@dataclass
class AuditEvent:
    """One audit log row. ``payload`` is event-specific (see module doc)."""
    ts: float
    kind: str
    agent: str = "system"
    goal_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        # Strip reserved keys from payload before the spread: a payload key
        # named v/ts/kind/agent/goal_id would otherwise clobber the canonical
        # structural field, losing it and corrupting the signed-hash input.
        _reserved = {"v", "ts", "kind", "agent", "goal_id"}
        safe_payload = {k: val for k, val in self.payload.items() if k not in _reserved}
        return {
            "v": self.schema_version,
            "ts": self.ts,
            "kind": self.kind,
            "agent": self.agent,
            "goal_id": self.goal_id,
            **safe_payload,
        }
