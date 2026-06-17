"""Federated swarm protocol (roadmap: 2028 H2 capabilities + ecosystem).

Two Maverick swarms peer and delegate goals to each other. The wire contract
is ``grpc_api/federation.proto`` (Hello / DelegateGoal / GoalStatus); this
module is the protocol layer behind it:

* :class:`FederationNode` — the client half: the registry of configured peers
  plus ``hello()`` (discovery: the peer's A2A Agent Card, validated via
  :func:`maverick.a2a.parse_remote_card`) and ``delegate()`` / ``status()``.
* :class:`FederationService` — the serve half: authenticates the caller,
  narrows the requested capabilities against a local grant
  (:func:`maverick.capability_boot.negotiate_boot` — narrow-only, a peer can
  never obtain authority this node wouldn't grant), and accepts a delegation
  by creating a local goal through the injected world/dispatcher seam
  (:class:`maverick.grpc_api.service.GoalService`; the orchestrator is never
  imported).

Auth is a shared per-peer token, fail-CLOSED: the receiver constant-time
compares the presented token against each configured peer's token, and the
matching ``[federation]`` entry *identifies* the caller — audit rows name the
peer from local config, never from the wire. Missing/unknown token = refused.

**Signed identity (Phase 2).** When the Agent Trust Plane is engaged and a peer
has a pinned Ed25519 key in ``[agent_trust]``, the shared token is no longer
sufficient: the caller signs the canonical delegation envelope
(:data:`DELEGATE_SCHEMA`) with its audit key and the receiver verifies it
against the pinned key (:func:`maverick.agent_trust.verify_identity`), with a
freshness window and a replay-nonce cache. ``[agent_trust] require_signed``
extends this to refuse shared-token-only peers. Node names used as signing
origins must be valid lowercase origins (``federation_envelope`` charset), which
the registry ids already are.

Both halves of every delegation are recorded with the reciprocity convention
``maverick.audit.federation`` verifies — the caller logs ``{peer_node,
correlation_id, direction: "sent"}``, the receiver ``{..., direction:
"received"}`` (kind :data:`EventKind.FEDERATION_DELEGATE`) — so a node that
drops its half of a cross-swarm event is detectable by ``cross_verify``.

Transport seam: anything with ``call(method, payload_dict) -> payload_dict``.
``FederationService.call`` itself satisfies it, so tests (or an in-process
loopback) wire client to service with no gRPC at all; the gRPC binding
(:func:`serve` + the default client transport) is a thin adapter over the same
dicts, lazy behind the ``[grpc]`` extra.

Off by default. Opt in::

    [federation]
    enabled = true                 # serve side; outbound needs peers only
    node = "atlas"                 # this node's name in its peers' configs
    peers = [
      { name = "vega", target = "vega.internal:50061", token = "${FED_VEGA_TOKEN}" },
    ]
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import time
import uuid
from collections import OrderedDict
from collections.abc import Iterable
from concurrent import futures
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .a2a import build_agent_card, parse_remote_card
from .audit.events import EventKind
from .capability_boot import negotiate_boot

log = logging.getLogger(__name__)

PROTOCOL = "maverick-federation/1"
# Schema of the signed delegation envelope (Phase 2 signed-identity). The caller
# signs it with its audit Ed25519 key; the receiver verifies against the pinned
# key in [agent_trust]. Possession of a leaked shared token alone no longer
# impersonates a peer that has a pinned key.
DELEGATE_SCHEMA = "maverick-federation-delegate/1"
_SIGN_FRESHNESS_S = 300.0  # accept a signature within ±5 min of now (replay window)
_REPLAY_CACHE_MAX = 4096
# Module-level cache of verified signatures already seen, oldest-first, so a
# captured valid delegation can't be replayed within the freshness window.
_seen_sigs: OrderedDict[str, float] = OrderedDict()

_DEFAULT_ADDR = "127.0.0.1:50061"  # one port up from the goal API (50051)
_DEFAULT_RPC_TIMEOUT_S = 10.0

# Sentinel: "no grant injected" (build from config) vs an explicit None
# (capability enforcement off -> delegations run unrestricted).
_UNSET = object()


class FederationError(ValueError):
    """A peer/request the federation layer refuses to deal with."""


class FederationAuthError(FederationError):
    """Missing or invalid shared token (fail-closed)."""


# -- config ----------------------------------------------------------------

def federation_enabled() -> bool:
    """Opt-in gate for the serving surface. Off by default (outward-facing)."""
    env = os.environ.get("MAVERICK_FEDERATION_ENABLED")
    if env is not None:
        return env.strip().lower() in {"1", "true", "yes", "on"}
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("federation") or {}
        val = cfg.get("enabled", False)
    except Exception:
        return False
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return bool(val)


def node_name() -> str:
    """This node's name — what its peers call it in *their* configs."""
    env = (os.environ.get("MAVERICK_FEDERATION_NODE") or "").strip()
    if env:
        return env
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("federation") or {}
        name = str(cfg.get("node") or "").strip()
    except Exception:
        name = ""
    return name or "maverick"


@dataclass(frozen=True)
class Peer:
    """One ``[federation] peers`` entry."""
    name: str    # the peer's node name (must match what it calls itself)
    target: str  # host:port its federation server listens on
    token: str = ""  # shared secret for this pair; "" can never authenticate


def load_peers(cfg: dict | None = None) -> list[Peer]:
    """Parse ``[federation] peers``. Forgiving: junk entries are skipped,
    duplicates keep the first occurrence, and nothing here ever raises."""
    if cfg is None:
        try:
            from .config import load_config
            cfg = load_config() or {}
        except Exception:
            return []
    fed = cfg.get("federation")
    raw = fed.get("peers") if isinstance(fed, dict) else None
    if not isinstance(raw, list):
        return []
    peers: list[Peer] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        target = str(entry.get("target") or "").strip()
        if not name or not target or name in seen:
            continue
        seen.add(name)
        peers.append(Peer(name=name, target=target,
                          token=str(entry.get("token") or "")))
    return peers


def _match_token(peers: Iterable[Peer], token: str) -> Peer | None:
    """Constant-time token -> peer; ``None`` when nothing matches (fail-closed).

    Scans every peer without an early exit so timing doesn't reveal which
    entry matched; a peer configured with an empty token never authenticates.
    """
    presented = (token or "").encode()
    matched: Peer | None = None
    for p in peers:
        if p.token and hmac.compare_digest(p.token.encode(), presented):
            matched = matched or p
    return matched


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _default_record(kind: str, **kw: Any) -> None:
    """Default audit seam -> :func:`maverick.audit.record`. Never raises:
    an audit-path failure must not break a delegation (the writer itself is
    already fail-safe; this also covers a stripped/vendored audit package)."""
    try:
        from .audit import record
        record(kind, **kw)
    except Exception as e:
        log.warning("federation: audit record failed: %s", e)


def _redact(text: str) -> str:
    """Strip detectable secrets from one field (best-effort, never raises)."""
    try:
        from .safety.secret_detector import redact
        out, _ = redact(str(text or ""))
        return out
    except Exception:  # pragma: no cover - redaction never blocks
        return str(text or "")


def _shield_block(text: str) -> str | None:
    """Shield-scan external agent text; a block reason, or ``None`` to allow.

    Fail-toward-gate on a scan *error* (a broken shield blocks rather than
    waves external traffic through); a shield that simply isn't installed
    allows (kernel rule 1 — the shield is optional), so an operator who chose
    not to install it isn't locked out of federation. Callers invoke this only
    when the trust plane is engaged.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        from maverick_shield import Shield  # type: ignore
    except Exception:
        return None  # shield not installed -> nothing to scan with
    try:
        verdict = Shield().scan_input(text)
        if not getattr(verdict, "allowed", True):
            return "; ".join(getattr(verdict, "reasons", []) or ["blocked by shield"])
    except Exception as e:  # pragma: no cover - fail toward the gate
        log.warning("federation: shield scan failed (blocking): %s", e)
        return "shield scan error"
    return None


# -- signed-identity (Phase 2) ---------------------------------------------

def require_signed() -> bool:
    """Must inbound delegations carry a valid signature against the peer's
    pinned key? On via ``MAVERICK_FEDERATION_REQUIRE_SIGNED`` or
    ``[agent_trust] require_signed = true``. Independent of having a pinned key:
    a peer WITH a pinned key is always signature-checked; this knob additionally
    refuses peers that have *no* pinned key (closing the shared-token-only path)."""
    env = os.environ.get("MAVERICK_FEDERATION_REQUIRE_SIGNED")
    if env is not None and env.strip() != "":
        return env.strip().lower() in {"1", "true", "yes", "on"}
    try:
        from .config import load_config
        return bool((load_config() or {}).get("agent_trust", {}).get("require_signed"))
    except Exception:
        return False


def _delegate_envelope(
    node: str, audience: str, corr: str, title: str, description: str,
    requested_tools: Iterable[str], max_risk: str | None, deadline_ms: int,
    created_at: float,
) -> dict[str, Any]:
    """The canonical delegation body both halves sign/verify byte-for-byte.

    ``origin`` is the SIGNER's node name and ``audience`` is the intended
    receiver node. The receiver reconstructs both from local configuration, so a
    signature only verifies for the configured caller/recipient pair and cannot
    be replayed to a different trusting node.
    """
    return {
        "schema": DELEGATE_SCHEMA,
        "origin": node,
        "audience": audience,
        "created_at": created_at,
        "correlation_id": corr,
        "goal_title": title,
        "goal_description": description,
        "requested_tools": sorted(str(t) for t in requested_tools),
        "max_risk": max_risk or "",
        "deadline_ms": _to_int(deadline_ms),
    }


def _fresh(created_at: float, *, now: float | None = None) -> bool:
    if not created_at or created_at <= 0:
        return False
    now = time.time() if now is None else now
    return abs(now - created_at) <= _SIGN_FRESHNESS_S


def _replay_seen(sig: str) -> bool:
    """Check-and-remember a verified signature; True if already seen (replay)."""
    if not sig:
        return False
    if sig in _seen_sigs:
        return True
    _seen_sigs[sig] = time.time()
    while len(_seen_sigs) > _REPLAY_CACHE_MAX:
        _seen_sigs.popitem(last=False)
    return False


def _sign_delegation(
    node: str, audience: str, corr: str, title: str, description: str,
    requested_tools: Iterable[str], max_risk: str | None, deadline_ms: int,
) -> dict[str, Any]:
    """Return ``{sig, pubkey, key_id, created_at}`` for a delegation, or ``{}``
    when signing is unavailable (no ``cryptography``) — an unsigned delegation
    is still sent (a receiver that requires a signature will refuse it)."""
    created_at = time.time()
    try:
        from . import federation_envelope
        env = _delegate_envelope(node, audience, corr, title, description,
                                 requested_tools, max_risk, deadline_ms,
                                 created_at)
        signed = federation_envelope.sign_envelope(env)
        return {"sig": signed["sig"], "pubkey": signed["pubkey"],
                "key_id": signed["key_id"], "created_at": created_at}
    except Exception as e:  # signing optional; receiver policy decides
        log.debug("federation: delegation signing unavailable: %s", e)
        return {}


# -- client half -----------------------------------------------------------

@dataclass(frozen=True)
class DelegateOutcome:
    """What :meth:`FederationNode.delegate` resolves to."""
    peer: str
    correlation_id: str
    accepted: bool
    goal_id: int | None = None  # the PEER-local goal id, when accepted
    reason: str = ""


class FederationNode:
    """The client half: this node's registry of peers + outbound operations.

    ``transport_factory(peer)`` returns the transport for one peer — anything
    with ``call(method, payload) -> payload``. The default is the gRPC adapter
    behind the ``[grpc]`` extra; tests inject fakes (a
    :class:`FederationService` instance itself satisfies the seam, giving an
    in-process loopback federation). ``record`` is the audit seam (defaults to
    ``maverick.audit.record``).
    """

    def __init__(
        self,
        *,
        node: str | None = None,
        peers: list[Peer] | None = None,
        transport_factory: Any | None = None,
        record: Any | None = None,
    ):
        self.node = (node or node_name()).strip()
        self.peers: dict[str, Peer] = {
            p.name: p for p in (load_peers() if peers is None else peers)
        }
        self._transport_factory = transport_factory or _grpc_transport
        self._transports: dict[str, Any] = {}
        self._record = record or _default_record

    def peer(self, name: str) -> Peer:
        p = self.peers.get(name)
        if p is None:
            raise FederationError(f"unknown federation peer: {name!r}")
        return p

    def _call(self, peer: Peer, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        transport = self._transports.get(peer.name)
        if transport is None:
            transport = self._transport_factory(peer)
            self._transports[peer.name] = transport
        return dict(transport.call(method, payload) or {})

    def _assert_outbound(self, peer: Peer) -> None:
        """Refuse to dial a peer the trust plane forbids outbound.

        Covers ``hello``/``status`` too — not just ``delegate`` — so a peer
        marked ``direction="inbound"`` (must not be dialed) can't be probed for
        its agent card or polled. No-op when the plane is disengaged; records an
        attributed denial and raises :class:`FederationError` when engaged.
        """
        from . import agent_trust
        out = agent_trust.decide_outbound(peer.name)
        if out.denied:
            agent_trust.record_denied(peer.name, out, direction="outbound")
            raise FederationError(f"outbound to peer {peer.name!r} refused: {out.reason}")

    def hello(self, peer_name: str) -> dict[str, Any]:
        """Discovery handshake -> the peer's parsed A2A agent card.

        Refuses (raises) a peer that speaks a different protocol version or
        whose card fails A2A validation (:func:`a2a.parse_remote_card` raises
        ``ValueError``) — never delegate against a card you couldn't read.
        """
        peer = self.peer(peer_name)
        self._assert_outbound(peer)
        reply = self._call(peer, "Hello", {
            "node": self.node, "protocol": PROTOCOL, "auth_token": peer.token,
        })
        proto = str(reply.get("protocol") or "")
        if proto != PROTOCOL:
            raise FederationError(
                f"peer {peer.name!r} speaks {proto or 'no protocol'!r}, "
                f"expected {PROTOCOL!r}")
        try:
            card = json.loads(str(reply.get("agent_card_json") or ""))
        except json.JSONDecodeError as e:
            raise FederationError(
                f"peer {peer.name!r} sent an unparseable agent card: {e}") from e
        return parse_remote_card(card)

    def delegate(
        self,
        peer_name: str,
        title: str,
        description: str = "",
        *,
        requested_tools: Iterable[str] = (),
        max_risk: str | None = None,
        correlation_id: str | None = None,
        deadline_ms: int = 0,
    ) -> DelegateOutcome:
        """Delegate one goal to a peer swarm and record our "sent" audit half.

        ``requested_tools`` are REQUIRED capabilities: the peer refuses unless
        its local grant can supply every one (narrow-only on its side). The
        ``correlation_id`` (auto-generated when omitted) links the two audit
        halves; ``deadline_ms`` rides as both the RPC deadline and the peer's
        wall-clock cap for the run. Transport failures resolve to a refused
        outcome (fail-honest, like the gRPC dispatcher) — and still record the
        attempt, so a half the peer never logged shows up in reciprocity checks.
        """
        peer = self.peer(peer_name)
        corr = (correlation_id or "").strip() or uuid.uuid4().hex
        # Egress control: a company governs which outside agents its agents may
        # *dial*. Disengaged -> no-op; engaged -> a peer absent from the trust
        # registry (or not permitted outbound) is refused before any connection
        # opens, and the refusal is still recorded for reciprocity.
        from . import agent_trust
        enforced, registry = agent_trust.load_trust_state()
        out = agent_trust.decide_outbound(peer.name, registry=registry,
                                          enforced=enforced)
        if out.denied:
            agent_trust.record_denied(
                peer.name, out, direction="outbound", correlation_id=corr)
            self._record(
                EventKind.FEDERATION_DELEGATE, agent="federation",
                peer_node=peer.name, correlation_id=corr, direction="sent",
                accepted=False, reason=out.reason,
            )
            return DelegateOutcome(peer=peer.name, correlation_id=corr,
                                   accepted=False, reason=out.reason)
        # Data-egress screening: delegating a goal ships its title/description to
        # a third-party swarm — the same exposure tier as a cloud LLM call. When
        # the plane is engaged, redact detectable secrets and shield-scan the
        # text before it leaves the boundary, refusing (fail-toward-gate) on a
        # block. Disengaged keeps the prior pass-through behaviour (rule 1).
        if enforced:
            block = _shield_block(title) or _shield_block(description)
            if block:
                reason = f"outbound delegation blocked by safety screen: {block}"
                agent_trust.record_denied(
                    peer.name, direction="outbound", correlation_id=corr,
                    rule="egress_screen", reason=reason)
                self._record(
                    EventKind.FEDERATION_DELEGATE, agent="federation",
                    peer_node=peer.name, correlation_id=corr, direction="sent",
                    accepted=False, reason=reason,
                )
                return DelegateOutcome(peer=peer.name, correlation_id=corr,
                                       accepted=False, reason=reason)
            title, description = _redact(title), _redact(description)
        tools_sorted = sorted({str(t) for t in requested_tools})
        # Sign the (post-redaction) delegation so a receiver can verify our
        # identity against our pinned key, not just our shared token. Best-effort
        # — an unsigned delegation is still sent and a receiver decides whether
        # to require the signature.
        deadline_i = _to_int(deadline_ms)
        signed = _sign_delegation(self.node, peer.name, corr, title, description,
                                  tools_sorted, max_risk, deadline_i)
        payload = {
            "goal_title": title,
            "goal_description": description,
            "correlation_id": corr,
            "requested_tools": tools_sorted,
            "max_risk": max_risk or "",
            "deadline_ms": deadline_i,
            "auth_token": peer.token,
            **signed,
        }
        try:
            reply = self._call(peer, "DelegateGoal", payload)
        except Exception as e:
            log.warning("federation: delegation to %s failed: %s", peer.name, e)
            reply = {"accepted": False, "reason": f"transport error: {e}"}
        accepted = bool(reply.get("accepted"))
        goal_id = _to_int(reply.get("goal_id")) or None
        reason = str(reply.get("reason") or "")
        self._record(
            EventKind.FEDERATION_DELEGATE, agent="federation",
            peer_node=peer.name, correlation_id=corr, direction="sent",
            accepted=accepted, remote_goal_id=goal_id, reason=reason,
        )
        return DelegateOutcome(peer=peer.name, correlation_id=corr,
                               accepted=accepted, goal_id=goal_id, reason=reason)

    def status(self, peer_name: str, goal_id: int) -> tuple[str, str]:
        """Poll a delegated goal -> ``(status, result)``; ``("unknown", "")``
        when the peer has no such goal."""
        peer = self.peer(peer_name)
        self._assert_outbound(peer)
        reply = self._call(peer, "GoalStatus", {
            "goal_id": _to_int(goal_id), "auth_token": peer.token,
        })
        return str(reply.get("status") or "unknown"), str(reply.get("result") or "")


# -- serve half ------------------------------------------------------------

class FederationService:
    """The serve half. Transport-agnostic: :meth:`call` takes and returns
    plain dicts, so it satisfies the same seam the client consumes (pass a
    service AS the transport for an in-process loopback federation).

    Dependency seams (all injected; production defaults in parentheses):

    * ``peers`` — who may call us + their tokens (``load_peers()``).
    * ``local_grant`` — the ``Capability`` ceiling delegations narrow against
      (``capability_from_config("federation:<node>")``); pass ``None``
      explicitly to run unrestricted (capability enforcement off).
    * ``goal_service`` — creates/dispatches/reports local goals
      (:class:`maverick.grpc_api.service.GoalService` — the world/dispatcher
      seam; the orchestrator is never imported).
    * ``record`` — the audit writer (``maverick.audit.record``).
    """

    def __init__(
        self,
        *,
        node: str | None = None,
        peers: list[Peer] | None = None,
        local_grant: Any = _UNSET,
        goal_service: Any | None = None,
        record: Any | None = None,
    ):
        self.node = (node or node_name()).strip()
        self._peers = load_peers() if peers is None else list(peers)
        self._grant = local_grant
        self._goal_service = goal_service
        self._record = record or _default_record

    # Lazy so constructing the service never touches config/world unless used.
    def _local_grant(self) -> Any:
        if self._grant is _UNSET:
            try:
                from .capability import capability_from_config
                self._grant = capability_from_config(f"federation:{self.node}")
            except Exception:  # fail-open on the read; auth still gates entry
                self._grant = None
        return self._grant

    def _goals(self) -> Any:
        if self._goal_service is None:
            from .grpc_api.service import GoalService
            self._goal_service = GoalService()
        return self._goal_service

    def _authenticate(self, payload: dict[str, Any]) -> Peer | None:
        return _match_token(self._peers, str(payload.get("auth_token") or ""))

    def _verify_signed(
        self, peer: Peer, agent: Any, payload: dict[str, Any],
        registry: dict[str, Any], enforced: bool,
    ) -> str | None:
        """Verify the delegation's signature against the peer's pinned key.

        Returns a refusal reason, or ``None`` to proceed. Only active when the
        trust plane is engaged and the peer is registered. A peer WITH a pinned
        key is always checked (a leaked token isn't enough); a peer WITHOUT one
        is allowed through on the shared token alone unless ``require_signed`` —
        the migration path. Freshness + replay-cache guard captured signatures.
        """
        if not enforced or agent is None:
            return None
        pinned = bool(getattr(agent, "pubkey", ""))
        if not pinned:
            if require_signed():
                return ("signed delegation required but no pinned key is "
                        f"configured for peer {peer.name!r}")
            return None  # migration: shared-token-only peer
        sig = str(payload.get("sig") or "")
        if not sig:
            return "signed delegation required: no signature present"
        if not _fresh(float(payload.get("created_at") or 0)):
            return "delegation signature is stale or future-dated"
        env = _delegate_envelope(
            peer.name, self.node, str(payload.get("correlation_id") or ""),
            str(payload.get("goal_title") or ""),
            str(payload.get("goal_description") or ""),
            payload.get("requested_tools") or [],
            str(payload.get("max_risk") or "") or None,
            _to_int(payload.get("deadline_ms")),
            float(payload.get("created_at") or 0),
        )
        env["pubkey"] = str(payload.get("pubkey") or "")
        env["key_id"] = str(payload.get("key_id") or "")
        env["sig"] = sig
        from . import agent_trust
        ok, reason = agent_trust.verify_identity(
            peer.name, env, expected_schema=DELEGATE_SCHEMA, registry=registry)
        if not ok:
            return f"delegation signature rejected: {reason}"
        if _replay_seen(sig):
            return "replayed delegation signature"
        return None

    @staticmethod
    def _governance_block(peer: Peer, decision: Any, req_risk: str | None) -> str | None:
        """Org-policy gate for accepting a delegation. Returns a refusal reason
        or ``None``. Pure no-op when no ``[governance]`` policy is configured.

        ``capability=None`` is passed deliberately: the *tool* ceiling was
        already enforced by boot negotiation, so this evaluates the org policy
        (deny/require-human action lists + risk floors) against the synthetic
        ``federation_delegate`` action, not against the agent's tool grant.
        """
        try:
            from .governance import Decision, evaluate
            verdict = evaluate("federation_delegate", risk=req_risk, capability=None)
        except Exception as e:  # pragma: no cover - governance never breaks the path
            log.debug("federation: governance eval skipped: %s", e)
            return None
        if verdict.decision is Decision.DENY:
            return f"denied by org governance policy ({verdict.rule}): {verdict.reason}"
        if verdict.decision is Decision.REQUIRE_HUMAN:
            return (f"delegation requires human approval ({verdict.rule}): "
                    f"{verdict.reason} — refused (no synchronous approval path)")
        return None

    def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Transport-seam entry point — same signature the client consumes."""
        payload = payload or {}
        if method == "Hello":
            return self.hello(payload)
        if method == "DelegateGoal":
            return self.delegate_goal(payload)
        if method == "GoalStatus":
            return self.goal_status(payload)
        raise FederationError(f"unknown federation method: {method!r}")

    def hello(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._authenticate(payload) is None:
            raise FederationAuthError("federation: missing or invalid token")
        return {
            "node": self.node,
            "protocol": PROTOCOL,
            "agent_card_json": json.dumps(build_agent_card()),
        }

    def delegate_goal(self, payload: dict[str, Any]) -> dict[str, Any]:
        corr = str(payload.get("correlation_id") or "").strip()
        peer = self._authenticate(payload)
        if peer is None:
            # Forensic row, deliberately unattributed: a name offered by an
            # unauthenticated caller can't be trusted, and a row without a
            # peer field never pairs in reciprocity checks.
            self._record(
                EventKind.FEDERATION_DELEGATE, agent="federation",
                correlation_id=corr, direction="received",
                accepted=False, reason="unauthorized",
            )
            return self._refuse("unauthorized: missing or invalid token")
        if not corr:
            return self._refuse_recorded(peer, corr, "correlation_id is required")

        requested = {str(t) for t in (payload.get("requested_tools") or [])
                     if str(t).strip()}
        req_risk = str(payload.get("max_risk") or "") or None

        # Agent Trust Plane: the single gate for *external* agents. Disengaged
        # (the default) this is a no-op ALLOW with no ceiling, so behaviour is
        # unchanged. Engaged (enterprise mode or [agent_trust] enforce), a peer
        # absent from the registry is refused here even though it presented a
        # valid shared token — registry membership, direction, and the tool/risk
        # ceiling are all checked before we equip a delegation.
        from . import agent_trust
        enforced, registry = agent_trust.load_trust_state()
        decision = agent_trust.decide_inbound(
            peer.name, requested_tools=requested, max_risk=req_risk,
            registry=registry, enforced=enforced)
        if decision.denied:
            agent_trust.record_denied(
                peer.name, decision, direction="inbound", correlation_id=corr)
            return self._refuse_recorded(peer, corr, decision.reason)

        # Signed-identity: prove the caller holds the peer's pinned private key,
        # not merely a copyable shared token. No-op when disengaged or the peer
        # has no pinned key (unless require_signed). Fail-closed on bad/stale/
        # replayed signatures.
        sig_reason = self._verify_signed(peer, decision.agent, payload,
                                         registry, enforced)
        if sig_reason:
            agent_trust.record_denied(
                peer.name, direction="inbound", correlation_id=corr,
                rule="unsigned", reason=sig_reason)
            return self._refuse_recorded(peer, corr, sig_reason)

        # Org governance: accepting a delegation is itself a consequential action
        # an org policy may gate. When engaged, run it through the same PDP that
        # gates tool calls: DENY refuses; REQUIRE_HUMAN refuses fail-closed (a
        # synchronous delegation can't pause for sign-off, so it is rejected
        # pending human approval rather than silently auto-accepted). No-op with
        # no [governance] policy configured, so non-governed deployments are
        # unaffected across the board.
        if enforced:
            gov_reason = self._governance_block(peer, decision, req_risk)
            if gov_reason:
                agent_trust.record_denied(
                    peer.name, direction="inbound", correlation_id=corr,
                    rule="governance", reason=gov_reason)
                return self._refuse_recorded(peer, corr, gov_reason)

        # Screen inbound external goal text for prompt-injection before it runs
        # in our orchestrator (fail-toward-gate). Only when engaged, so the
        # default personal-agent path is unchanged (kernel rule 1).
        if enforced:
            block = (_shield_block(payload.get("goal_title"))
                     or _shield_block(payload.get("goal_description")))
            if block:
                return self._refuse_recorded(
                    peer, corr, f"inbound goal blocked by safety screen: {block}")

        # Narrow-only: the peer's request can only restrict this node's own
        # grant, and every requested tool is REQUIRED — a delegation this node
        # can't fully equip is refused rather than run half-equipped. When the
        # trust plane is engaged, the peer's registry ceiling tightens the local
        # grant too (intersection, never a broadening).
        parent = self._local_grant()
        if decision.capability is not None:
            parent = (decision.capability if parent is None
                      else parent.intersect(decision.capability,
                                            principal=f"federation:{peer.name}"))
        negotiation = negotiate_boot(
            parent,
            principal=f"federation:{peer.name}",
            requested_tools=requested or None,
            required_tools=requested or None,
            max_risk=req_risk,
        )
        if not negotiation.ok:
            return self._refuse_recorded(peer, corr, negotiation.reason)

        deadline_ms = _to_int(payload.get("deadline_ms"))
        # Clamp the run's budget to the peer's registry ceiling (down only):
        # both wall-clock AND dollars. max_dollars was previously parsed and
        # advertised but enforced nowhere — wire it into the delegated run.
        capped_dollars, capped_wall = agent_trust.clamp_budget(
            decision.agent,
            max_wall_seconds=(deadline_ms / 1000.0) if deadline_ms > 0 else None,
        )
        if capped_wall is not None:
            deadline_ms = int(capped_wall * 1000.0)
        try:
            goal_id = int(self._goals().start_goal(
                str(payload.get("goal_title") or ""),
                str(payload.get("goal_description") or ""),
                max_dollars=capped_dollars,
                max_wall_seconds=(deadline_ms / 1000.0) if deadline_ms > 0 else None,
                channel="federation",
                user_id=f"federation:{peer.name}",
                capability=negotiation.granted,
            ))
        except ValueError as e:  # e.g. empty title
            return self._refuse_recorded(peer, corr, str(e))
        self._record(
            EventKind.FEDERATION_DELEGATE, agent="federation", goal_id=goal_id,
            peer_node=peer.name, correlation_id=corr, direction="received",
            accepted=True, reason="",
        )
        return {"accepted": True, "goal_id": goal_id, "reason": ""}

    def goal_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._authenticate(payload) is None:
            raise FederationAuthError("federation: missing or invalid token")
        st = self._goals().status(_to_int(payload.get("goal_id")))
        if st is None:
            return {"status": "unknown", "result": ""}
        return {"status": str(st.status), "result": str(st.result or "")}

    @staticmethod
    def _refuse(reason: str) -> dict[str, Any]:
        return {"accepted": False, "goal_id": 0, "reason": reason}

    def _refuse_recorded(self, peer: Peer, corr: str, reason: str) -> dict[str, Any]:
        """Refuse, recording our "received" half so the caller's "sent" row
        still reciprocates (a refusal is a cross-swarm event too)."""
        self._record(
            EventKind.FEDERATION_DELEGATE, agent="federation",
            peer_node=peer.name, correlation_id=corr, direction="received",
            accepted=False, reason=reason,
        )
        return self._refuse(reason)


# -- gRPC binding (thin adapter over the dict seam; [grpc] extra, all lazy) --

_PROTO = Path(__file__).with_name("grpc_api") / "federation.proto"


def _require_grpc():
    try:
        import grpc
    except ImportError as e:
        raise ImportError(
            "grpc not installed (needed for federated swarms over gRPC). "
            "Run: pip install 'maverick-agent[grpc]'"
        ) from e
    return grpc


def _load_stubs():
    """Import the generated pb2 modules, generating them first if absent.

    Same scheme as ``grpc_plugin_host``: stubs compile on demand from the
    bundled ``federation.proto``, rooted at the directory containing
    ``maverick/`` so the generated pair imports package-qualified
    (``from maverick.grpc_api import federation_pb2 ...``) from anywhere.
    """
    try:
        from .grpc_api import federation_pb2, federation_pb2_grpc  # type: ignore
        return federation_pb2, federation_pb2_grpc
    except ImportError:
        _generate_stubs()
        from .grpc_api import federation_pb2, federation_pb2_grpc  # type: ignore
        return federation_pb2, federation_pb2_grpc


def _generate_stubs() -> None:
    try:
        from grpc_tools import protoc
    except ImportError as e:
        raise ImportError(
            "grpcio-tools not installed (needed to generate stubs). "
            "Run: pip install 'maverick-agent[grpc]'"
        ) from e
    root = _PROTO.parents[2]
    rc = protoc.main([
        "protoc",
        f"-I{root}",
        f"--python_out={root}",
        f"--grpc_python_out={root}",
        str(_PROTO),
    ])
    if rc != 0:  # pragma: no cover -- only on a broken protoc toolchain
        raise RuntimeError(f"protoc failed to generate federation stubs (rc={rc})")


def _grpc_code():
    import grpc
    return grpc.StatusCode


def _abort(context, code, details: str):
    context.abort(code, details)
    raise PermissionError(details)  # pragma: no cover -- grpc abort always raises


class _GrpcTransport:
    """``transport.call`` over a real channel — the default client adapter."""

    def __init__(self, peer: Peer):
        self.peer = peer
        self._stub = None
        self._pb2 = None

    def _bind(self):
        if self._stub is None:
            grpc = _require_grpc()
            pb2, pb2_grpc = _load_stubs()
            channel = grpc.insecure_channel(self.peer.target)
            self._stub = pb2_grpc.MaverickFederationStub(channel)
            self._pb2 = pb2
        return self._stub, self._pb2

    def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        stub, pb2 = self._bind()
        payload = payload or {}
        deadline_ms = _to_int(payload.get("deadline_ms"))
        timeout = (deadline_ms / 1000.0) if deadline_ms > 0 else _DEFAULT_RPC_TIMEOUT_S
        token = str(payload.get("auth_token") or "")
        if method == "Hello":
            r = stub.Hello(pb2.HelloRequest(
                node=str(payload.get("node") or ""),
                protocol=str(payload.get("protocol") or ""),
                auth_token=token,
            ), timeout=timeout)
            return {"node": r.node, "protocol": r.protocol,
                    "agent_card_json": r.agent_card_json}
        if method == "DelegateGoal":
            r = stub.DelegateGoal(pb2.DelegateRequest(
                goal_title=str(payload.get("goal_title") or ""),
                goal_description=str(payload.get("goal_description") or ""),
                correlation_id=str(payload.get("correlation_id") or ""),
                requested_tools=[str(t) for t in payload.get("requested_tools") or []],
                max_risk=str(payload.get("max_risk") or ""),
                deadline_ms=deadline_ms,
                auth_token=token,
                sig=str(payload.get("sig") or ""),
                pubkey=str(payload.get("pubkey") or ""),
                key_id=str(payload.get("key_id") or ""),
                created_at=float(payload.get("created_at") or 0.0),
            ), timeout=timeout)
            return {"accepted": r.accepted, "goal_id": r.goal_id, "reason": r.reason}
        if method == "GoalStatus":
            r = stub.GoalStatus(pb2.StatusRequest(
                goal_id=_to_int(payload.get("goal_id")), auth_token=token,
            ), timeout=timeout)
            return {"status": r.status, "result": r.result}
        raise FederationError(f"unknown federation method: {method!r}")


def _grpc_transport(peer: Peer) -> _GrpcTransport:
    return _GrpcTransport(peer)


def _servicer(service: FederationService, pb2, pb2_grpc):
    """Map protobuf messages <-> the dict payloads :class:`FederationService`
    speaks. Auth refusals on Hello/GoalStatus abort UNAUTHENTICATED;
    DelegateGoal refusals are in-band per the proto contract."""

    class MaverickFederationServicer(pb2_grpc.MaverickFederationServicer):
        def Hello(self, request, context):
            try:
                reply = service.call("Hello", {
                    "node": request.node,
                    "protocol": request.protocol,
                    "auth_token": request.auth_token,
                })
            except FederationAuthError as e:
                _abort(context, _grpc_code().UNAUTHENTICATED, str(e))
                raise  # if context.abort() didn't raise (mocks), don't fall
                # through to reference the unbound `reply`
            return pb2.PeerInfo(
                node=reply["node"], protocol=reply["protocol"],
                agent_card_json=reply["agent_card_json"],
            )

        def DelegateGoal(self, request, context):
            del context  # refusals are in-band
            reply = service.call("DelegateGoal", {
                "goal_title": request.goal_title,
                "goal_description": request.goal_description,
                "correlation_id": request.correlation_id,
                "requested_tools": list(request.requested_tools),
                "max_risk": request.max_risk,
                "deadline_ms": request.deadline_ms,
                "auth_token": request.auth_token,
                # Optional signed-identity fields (additive proto fields); use
                # getattr so an older stub or a partial message degrades to
                # unsigned rather than raising.
                "sig": getattr(request, "sig", ""),
                "pubkey": getattr(request, "pubkey", ""),
                "key_id": getattr(request, "key_id", ""),
                "created_at": getattr(request, "created_at", 0.0),
            })
            return pb2.DelegateResult(
                accepted=bool(reply.get("accepted")),
                goal_id=_to_int(reply.get("goal_id")),
                reason=str(reply.get("reason") or ""),
            )

        def GoalStatus(self, request, context):
            try:
                reply = service.call("GoalStatus", {
                    "goal_id": request.goal_id,
                    "auth_token": request.auth_token,
                })
            except FederationAuthError as e:
                _abort(context, _grpc_code().UNAUTHENTICATED, str(e))
                raise  # if context.abort() didn't raise (mocks), don't fall
                # through to reference the unbound `reply`
            return pb2.StatusReply(status=reply["status"], result=reply["result"])

    return MaverickFederationServicer()


def serve(
    address: str = _DEFAULT_ADDR,
    *,
    service: FederationService | None = None,
    max_workers: int = 8,
):
    """Start the federation gRPC server. Returns the server handle.

    Opt-in and fail-closed twice over: refuses to start unless
    :func:`federation_enabled`, and a service with no configured peers (or
    peers without tokens) refuses every call.
    """
    if not federation_enabled():
        raise RuntimeError(
            "federation is disabled. Opt in with MAVERICK_FEDERATION_ENABLED=1 "
            "or [federation] enabled = true in ~/.maverick/config.toml."
        )
    grpc = _require_grpc()
    pb2, pb2_grpc = _load_stubs()
    if service is None:
        service = FederationService()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    pb2_grpc.add_MaverickFederationServicer_to_server(
        _servicer(service, pb2, pb2_grpc), server
    )
    server.add_insecure_port(address)
    server.start()
    log.info("Maverick federation listening on %s (node=%s)", address, service.node)
    return server


__all__ = [
    "PROTOCOL",
    "Peer",
    "DelegateOutcome",
    "FederationError",
    "FederationAuthError",
    "FederationNode",
    "FederationService",
    "federation_enabled",
    "load_peers",
    "node_name",
    "serve",
]
