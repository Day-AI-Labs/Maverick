"""Signed federation envelopes — the shared primitive for instance-to-instance
exchange (marketplace listings, channel messages).

An *envelope* is a flat JSON object carrying a ``schema`` tag
(``maverick-<thing>-fed/1``), the sender's ``origin`` name, a ``created_at``
timestamp, and the payload fields. It is signed with this host's audit
Ed25519 key (``maverick.audit.signing`` — the same keypair that signs the
audit chain, stored under ``data_dir("audit", "keys")``):

  - ``pubkey`` / ``key_id``: the signer's raw Ed25519 public key (hex) and
    fingerprint, included in the signed bytes;
  - ``sig``: Ed25519 signature over the SHA-256 of the canonical JSON
    (``sort_keys=True``) of every field except ``sig`` — byte-for-byte the
    convention ``audit.signing.AuditSigner`` uses for chain rows.

Trust model — **fail-closed, pinned keys**: verification only succeeds when
the envelope's ``origin`` appears in the operator's ``[federation]`` peer
list AND the signature verifies against the *pinned* public key configured
for that origin. The envelope's self-carried ``pubkey`` is never a trust
anchor (anyone can mint a key); it is informational and covered by the
signature. No peers configured means every import is rejected. A missing
``cryptography`` library also rejects — an unverifiable envelope is never
applied.

Peer list format (``~/.maverick/config.toml``)::

    [federation]
    origin = "my-instance"            # this host's name in outbound envelopes
    marketplace_peers = [
        { origin = "ops-eu", pubkey = "<64-hex Ed25519 raw public key>" },
    ]
    channel_peers = [
        { origin = "ops-eu", pubkey = "<64 hex>", secret = "<per-pair secret>" },
    ]

String entries ``"origin=pubkeyhex"`` are also accepted. Reciprocity is
per-direction: each side pins the other's key; there is no key exchange
protocol here — operators swap pubkeys out of band
(``data_dir("audit","keys")/<key_id>.pub``, hex-encoded).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re

log = logging.getLogger(__name__)

# Origins become path/name segments ("origin/name" namespacing, "fed:<origin>"
# channels), so the charset is locked down: no "/", no whitespace, 64 max.
_ORIGIN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
# Raw Ed25519 public key, hex-encoded: exactly 32 bytes.
_PUBKEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_MAX_PEERS = 64

DEFAULT_ORIGIN = "local"


class FederationError(Exception):
    """Raised when an envelope cannot be built (signing unavailable, bad input)."""


def valid_origin(origin: object) -> bool:
    return isinstance(origin, str) and bool(_ORIGIN_RE.fullmatch(origin))


def local_origin(cfg: dict | None = None) -> str:
    """This instance's origin name (``[federation] origin``), default "local"."""
    if cfg is None:
        try:
            from .config import load_config
            cfg = load_config() or {}
        except Exception:  # pragma: no cover - config never blocks reads
            cfg = {}
    origin = (cfg.get("federation") or {}).get("origin")
    if valid_origin(origin):
        return origin  # type: ignore[return-value]
    if origin:
        log.warning("[federation] origin %r is invalid (want %s); using %r",
                    origin, _ORIGIN_RE.pattern, DEFAULT_ORIGIN)
    return DEFAULT_ORIGIN


def peer_allowlist(kind: str, cfg: dict | None = None) -> dict[str, dict]:
    """Pinned peers from ``[federation] <kind>`` as ``{origin: entry}``.

    Entries are ``{origin, pubkey}`` tables (plus extra fields such as
    ``secret`` for channel peers) or ``"origin=pubkeyhex"`` strings. Malformed
    entries are skipped with a warning — they simply never match, which is the
    fail-closed direction. An unreadable config yields an empty allowlist
    (reject everything), never an exception.
    """
    if cfg is None:
        try:
            from .config import load_config
            cfg = load_config() or {}
        except Exception:
            log.warning("federation: config unreadable; peer allowlist is empty")
            return {}
    raw = (cfg.get("federation") or {}).get(kind)
    out: dict[str, dict] = {}
    if not isinstance(raw, list):
        if raw is not None:
            log.warning("[federation] %s must be a list; ignoring", kind)
        return out
    for item in raw[:_MAX_PEERS]:
        if isinstance(item, str):
            origin, _, pubkey = item.partition("=")
            entry: dict = {"origin": origin.strip(), "pubkey": pubkey.strip()}
        elif isinstance(item, dict):
            entry = dict(item)
        else:
            log.warning("[federation] %s: skipping non-table entry %r", kind, item)
            continue
        origin = str(entry.get("origin") or "")
        pubkey = str(entry.get("pubkey") or "")
        if not valid_origin(origin) or not _PUBKEY_RE.fullmatch(pubkey):
            log.warning("[federation] %s: skipping entry with bad origin/pubkey "
                        "(origin=%r)", kind, origin)
            continue
        entry["origin"] = origin
        entry["pubkey"] = pubkey.lower()
        out[origin] = entry
    return out


def _digest(payload: dict) -> str:
    """SHA-256 hex of the canonical JSON — same convention as audit chain rows."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def sign_envelope(payload: dict) -> dict:
    """Return a signed copy of ``payload`` (adds ``pubkey``/``key_id``/``sig``).

    Signs with this host's audit Ed25519 key (generated on first use). Raises
    :class:`FederationError` when ``cryptography`` is not installed — an
    *unsigned* federation export must never be produced.
    """
    from .audit import signing as audit_signing
    if not audit_signing._have_crypto():
        raise FederationError(
            "cryptography not installed; cannot sign federation envelopes. "
            "Run: pip install 'maverick-agent[audit-signing]'"
        )
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv, pub, key_id = audit_signing._load_or_create_keypair()
    signer = ed25519.Ed25519PrivateKey.from_private_bytes(priv)
    env = dict(payload)
    env.pop("sig", None)
    env["pubkey"] = pub.hex()
    env["key_id"] = key_id
    digest = _digest(env)
    env["sig"] = signer.sign(bytes.fromhex(digest)).hex()
    return env


def verify_envelope(
    envelope: object, *, expected_schema: str, peers: dict[str, dict]
) -> tuple[bool, str]:
    """Fail-closed envelope verification. Returns ``(ok, reason)``.

    Rejects (never raises) on: non-object envelope, schema mismatch, missing or
    malformed ``origin``, origin absent from ``peers``, envelope pubkey not
    matching the pinned key, missing ``cryptography`` (unverifiable = rejected),
    and signature failure. Verification is against the **pinned** key, so a
    valid signature under an attacker-minted key never passes.
    """
    if not isinstance(envelope, dict):
        return False, "envelope is not an object"
    if envelope.get("schema") != expected_schema:
        return False, f"unexpected schema {envelope.get('schema')!r}"
    origin = envelope.get("origin")
    if not valid_origin(origin):
        return False, "missing or malformed origin"
    sig = envelope.get("sig")
    pubkey = envelope.get("pubkey")
    if not isinstance(sig, str) or not sig:
        return False, "missing signature"
    if not isinstance(pubkey, str) or not pubkey:
        return False, "missing pubkey"
    peer = peers.get(origin)  # type: ignore[arg-type]
    if peer is None:
        return False, f"origin {origin!r} is not in the peer trust list"
    pinned = str(peer.get("pubkey") or "")
    if not pinned:
        return False, f"no pinned pubkey for origin {origin!r}"
    if not hmac.compare_digest(pubkey.lower(), pinned.lower()):
        return False, "envelope pubkey does not match the pinned key for this origin"
    from .audit import signing as audit_signing
    if not audit_signing._have_crypto():
        return False, "cryptography not installed; refusing to apply an unverifiable envelope"
    body = {k: v for k, v in envelope.items() if k != "sig"}
    if not audit_signing.verify_ed25519(pinned, sig, bytes.fromhex(_digest(body))):
        return False, "signature verification failed"
    return True, "ok"


__all__ = [
    "FederationError",
    "local_origin",
    "peer_allowlist",
    "sign_envelope",
    "verify_envelope",
    "valid_origin",
    "DEFAULT_ORIGIN",
]
