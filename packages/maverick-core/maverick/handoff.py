"""Verified agent-to-agent handoffs: the signed envelope + its verifier.

The **trust layer** for inter-agent delegation. Maverick already has the two
pieces this sits between:

  * :mod:`maverick.agent_bus` -- the *transport* (in-memory inboxes, ``send``/
    ``recv``), which deliberately does no auth ("just enough plumbing");
  * :mod:`maverick.capability` -- the *grant* (a signed, **attenuating**,
    principal-bound :class:`~maverick.capability.Capability`).

What was missing is the trust frame *between* them: when one agent hands a
sub-task to another, how does the receiver know the request is authentic, scoped,
and not replayed -- and run under exactly the delegated authority, no more? This
module is that frame (see ``docs/proposals/agent-to-agent-protocol.md`` §7, §9).

Not to be confused with :mod:`maverick.a2a`, which implements the *external*
Linux-Foundation A2A standard (Agent-Card discovery + the inbound task API,
bearer-auth). That is cross-vendor interop; this is the internal fleet's own
delegation trust. They compose: an external A2A call lands as a principal, then
internal work is delegated between agents via *these* signed handoffs.

The verifier is **pure and offline** (like :mod:`maverick.governance`) so the
trust decision is exhaustively unit-testable; wiring it onto the bus is a
separate step (a handoff Envelope is what rides as an ``agent_bus`` payload).

Trust model, from the proposal:

  * **authenticity** -- the grant is Ed25519-signed by a trusted issuer, and the
    whole envelope is signed by that same issuer (the supervisor mediates the
    handoff). An untrusted/forged signer is rejected; with ``cryptography`` absent
    the verifier **fails closed** ("verified" is meaningless without it).
  * **least privilege** -- the receiver runs under ``grant`` and nothing more
    (confused-deputy safe). Escalation is impossible because the grant was minted
    by *attenuating* the delegator's grant (:meth:`Capability.attenuate`); the
    verifier hands back exactly the grant to run under.
  * **integrity / non-repudiation** -- the signature covers every field, so no
    field can be altered (or a grant swapped in) without breaking it.
  * **freshness** -- a timestamp window plus a single-use nonce defeat replay.

Single-issuer anchoring is the first build; multi-hop lineage chains (a grant's
spawn chain resolving through several supervisors) are a future extension.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, replace

from .audit import signing
from .capability import Capability, sign_capability, verify_capability

INTENTS = ("handoff", "request", "response", "broadcast")


@dataclass(frozen=True)
class Envelope:
    """A signed inter-agent message. ``grant`` is the attenuated capability the
    recipient runs under; ``grant_sig``/``issuer_pub``/``sig`` are the trust frame
    (everything outside them is the work). The three signature fields are ``None``
    until :func:`mint_handoff` signs the envelope."""

    sender: str                 # delegating principal (the "from")
    recipient: str              # receiving principal; the grant is minted FOR it
    task: str                   # human-readable sub-task
    grant: Capability           # the attenuated capability the receiver runs under
    nonce: str
    ts: float
    intent: str = "handoff"
    required_tools: tuple[str, ...] = ()   # tools the task needs; must be in-scope
    body: str = ""
    grant_sig: str | None = None           # issuer signature over the grant
    issuer_pub: str | None = None          # issuing supervisor's pubkey (trust-anchored)
    sig: str | None = None                 # issuer signature over the whole envelope

    def _core(self) -> dict:
        """The fields the envelope signature binds (everything but ``sig``)."""
        return {
            "sender": self.sender,
            "recipient": self.recipient,
            "task": self.task,
            "grant": self.grant.signing_bytes().decode("utf-8"),
            "grant_sig": self.grant_sig,
            "issuer_pub": self.issuer_pub,
            "nonce": self.nonce,
            "ts": self.ts,
            "intent": self.intent,
            "required_tools": sorted(self.required_tools),
            "body": self.body,
        }

    def signing_bytes(self) -> bytes:
        """Canonical, stable serialization for signing/verification."""
        return json.dumps(self._core(), sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class HandoffVerdict:
    """Outcome of verifying an :class:`Envelope`. ``rule`` names the check that
    decided, for the audit record. On ``ok`` the ``grant`` is the (attenuated)
    capability the receiver MUST run under -- never its ambient authority."""

    ok: bool
    rule: str
    reason: str
    grant: Capability | None = None


class NonceCache:
    """Single-use nonce tracker (replay defense).

    In-memory and per-process; a live multi-node bus would back this with a
    shared store (the interface is the same). ``seen`` reports prior use;
    :func:`verify_handoff` calls ``remember`` only after a fully-valid handoff.
    When callers do not provide one, the verifier uses a process-local default
    cache so replay protection remains enabled by default."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def seen(self, nonce: str) -> bool:
        return nonce in self._seen

    def remember(self, nonce: str) -> None:
        self._seen.add(nonce)


_DEFAULT_NONCE_CACHE = NonceCache()


def _sign_ed25519(private_hex: str, data: bytes) -> str:
    """Ed25519-sign ``data``; hex signature. Mirrors :func:`capability.sign_capability`."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    priv = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex))
    return priv.sign(data).hex()


def mint_handoff(
    *,
    sender: str,
    recipient: str,
    task: str,
    grant: Capability,
    issuer_private_hex: str,
    issuer_pub_hex: str,
    intent: str = "handoff",
    required_tools=(),
    body: str = "",
    nonce: str | None = None,
    ts: float | None = None,
) -> Envelope:
    """Mint a signed handoff: the issuer (supervisor) signs both the attenuated
    ``grant`` and the whole envelope.

    ``grant.principal`` MUST equal ``recipient`` -- the grant is minted *for* the
    receiver, who runs under it. The grant must already be an attenuation of the
    delegator's grant (that is what makes escalation impossible); this function
    broadens nothing. Requires ``cryptography``.
    """
    if grant.principal != recipient:
        raise ValueError(
            "grant.principal must equal recipient (the grant is minted for the receiver)"
        )
    if intent not in INTENTS:
        raise ValueError(f"unknown intent {intent!r}; expected one of {INTENTS}")
    nonce = nonce or uuid.uuid4().hex
    ts = time.time() if ts is None else ts
    grant_sig = sign_capability(grant, issuer_private_hex)
    env = Envelope(
        sender=sender,
        recipient=recipient,
        task=task,
        grant=grant,
        nonce=nonce,
        ts=ts,
        intent=intent,
        required_tools=tuple(required_tools),
        body=body,
        grant_sig=grant_sig,
        issuer_pub=issuer_pub_hex,
    )
    return replace(env, sig=_sign_ed25519(issuer_private_hex, env.signing_bytes()))


def verify_handoff(
    env: Envelope,
    *,
    trusted_issuers,
    nonce_cache: NonceCache | None = None,
    now: float | None = None,
    max_age_s: float = 300.0,
    clock_skew_s: float = 60.0,
) -> HandoffVerdict:
    """Verify a handoff envelope. Returns a :class:`HandoffVerdict`; never raises.

    Checks, strictest/clearest first:
      0. crypto present (else fail closed -- "verified" is meaningless without it);
      1. structurally signed (issuer_pub + grant_sig + sig present);
      2. issuer is a **trusted** supervisor key;
      3. the **grant** is authentically signed by that issuer;
      4. the **envelope** is signed by that issuer (no field/grant tampered);
      5. the grant is bound to *this* recipient (no grant swap);
      6. intent is known;
      7. **fresh** -- not future-dated past the skew, not older than the window;
      8. **not replayed** -- the nonce is unused;
      9. **in scope** -- the grant is unexpired and permits every required tool.

    ``nonce_cache`` may be supplied by a bus or service to share replay state
    across workers. If omitted, a process-local cache is used so the exported
    verifier still enforces single-use nonces by default. On success the verdict
    carries the grant the receiver must run under.
    """
    now = time.time() if now is None else now
    nonce_cache = _DEFAULT_NONCE_CACHE if nonce_cache is None else nonce_cache

    if not signing._have_crypto():
        return HandoffVerdict(False, "no_crypto", "cryptography unavailable; cannot verify")
    if not (env.sig and env.grant_sig and env.issuer_pub):
        return HandoffVerdict(False, "unsigned", "missing issuer_pub / grant_sig / sig")
    if env.issuer_pub not in set(trusted_issuers):
        return HandoffVerdict(False, "untrusted_issuer",
                              f"issuer {env.issuer_pub[:16]}... is not a trusted supervisor")
    if not verify_capability(env.grant, env.grant_sig, env.issuer_pub):
        return HandoffVerdict(False, "bad_grant_sig", "the grant's signature does not verify")
    if not signing.verify_ed25519(env.issuer_pub, env.sig, env.signing_bytes()):
        return HandoffVerdict(False, "tampered", "the envelope signature does not verify")
    if env.grant.principal != env.recipient:
        return HandoffVerdict(False, "grant_recipient_mismatch",
                              f"grant is for {env.grant.principal!r}, not recipient {env.recipient!r}")
    if env.intent not in INTENTS:
        return HandoffVerdict(False, "bad_intent", f"unknown intent {env.intent!r}")
    if env.ts > now + clock_skew_s:
        return HandoffVerdict(False, "future_ts", "timestamp is in the future")
    if now - env.ts > max_age_s:
        return HandoffVerdict(False, "stale", f"older than the {max_age_s:.0f}s window")
    if nonce_cache.seen(env.nonce):
        return HandoffVerdict(False, "replay", "nonce has already been used")
    if env.grant.is_expired(now):
        return HandoffVerdict(False, "grant_expired", "the delegated grant has expired")
    for tool in env.required_tools:
        if not env.grant.permits(tool, now=now):
            return HandoffVerdict(False, "out_of_scope",
                                  f"grant does not permit required tool {tool!r}")

    nonce_cache.remember(env.nonce)
    return HandoffVerdict(True, "ok", "handoff verified", grant=env.grant)


__all__ = [
    "Envelope",
    "HandoffVerdict",
    "NonceCache",
    "mint_handoff",
    "verify_handoff",
    "INTENTS",
]
