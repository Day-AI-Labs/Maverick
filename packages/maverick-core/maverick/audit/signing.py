"""Audit-log Ed25519 signing.

Every audit event line is hashed together with the previous line's
hash (Merkle-style chain). The chain head is signed with an Ed25519
key whose pubkey is stored alongside.

This gives us tamper-evidence: if any historical line is altered,
the chain breaks at that point. The on-disk format stays NDJSON
(append-only), with two extra fields per row:

  - ``prev_hash``: hex-encoded SHA-256 of the previous row's signed bytes
  - ``hash``:      hex-encoded SHA-256 of this row's signed bytes
  - ``sig``:       hex-encoded Ed25519 signature of ``hash``

Key management:
  - First write: a new Ed25519 keypair is generated and saved at
    ``~/.maverick/audit/keys/<keyid>.{key,pub}`` (chmod 600 on the
    private key).
  - Subsequent writes load the most recent key.
  - ``verify_chain()`` walks a file and confirms every signature +
    chain link. Returns a list of any breaks for human review.

Externally-managed key (enterprise / H29): set
``MAVERICK_AUDIT_SIGNING_KEY`` to a raw 32-byte Ed25519 private key (hex or
base64). It then becomes the active signer and is held IN MEMORY ONLY -- the
private key is never written to the local key dir, so the chain's trust anchor
can be custodied in a KMS / HSM / secrets manager and injected at deploy time
instead of generated-and-left on the host. Maverick consumes and removes this
environment entry the first time audit signing loads, then caches only decoded
key material in memory; inherited startup environments are not an HSM/KMS
security boundary. Only the public half (plus an ``.injected`` marker) is
persisted, so local ``verify_chain`` still trusts the chain. An injected key
takes precedence over any on-disk key; rotate it in your secret manager (the
``key_id`` is derived from the public key, so a new key chains additively
exactly like ``rotate_audit_keypair``).

Optional [audit-signing] extra (cryptography>=44.0.1).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..paths import data_dir

log = logging.getLogger(__name__)


# Legacy single-tenant key dir, kept as a module-level attribute for
# back-compat: existing tests monkeypatch ``signing.KEY_DIR`` to isolate keys,
# so every key path is resolved through ``_key_dir()`` which honours that
# override. With no override, ``_key_dir()`` resolves the *tenant-scoped* dir
# via ``data_dir`` so each tenant gets an independent signing key, while the
# no-tenant default stays exactly ``~/.maverick/audit/keys``.
_LEGACY_KEY_DIR = data_dir("audit", "keys")
KEY_DIR = _LEGACY_KEY_DIR


class OffHostSigningRequiredError(RuntimeError):
    """Raised when audit signing must use off-host key material."""


def _key_dir() -> Path:
    """The active audit signing-key directory.

    Honours a monkeypatched ``KEY_DIR`` (tests pin it for isolation); otherwise
    routes through the tenant-aware path helper so each tenant gets its own key
    chain while the no-tenant default is the legacy ``~/.maverick/audit/keys``.
    """
    if KEY_DIR is not _LEGACY_KEY_DIR:
        return KEY_DIR
    from ..paths import data_dir

    return data_dir("audit", "keys")


_KEY_ID_RE = re.compile(r"^[0-9a-f]{16}$")

# Cross-file tip-ledger (#462/#443): a signed, chained ledger recording each
# completed day-file's tip hash + row count, so deleting or truncating a WHOLE
# day-file is detectable (per-file verify_chain only sees within one file).
ANCHOR_FILENAME = "anchors.ndjson"
ANCHOR_MARKER_FILENAME = ".anchors.required"
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _is_valid_key_id(key_id: str) -> bool:
    """Key IDs are fixed-width lowercase hex fingerprints."""
    return bool(_KEY_ID_RE.fullmatch(key_id))


def _key_paths_for_id(key_id: str) -> tuple[Path, Path] | tuple[None, None]:
    """Return trusted key paths for key_id, or (None, None) if invalid."""
    if not _is_valid_key_id(key_id):
        return None, None
    key_dir = _key_dir()
    pub_path = (key_dir / f"{key_id}.pub").resolve()
    priv_path = (key_dir / f"{key_id}.key").resolve()
    try:
        pub_path.relative_to(key_dir.resolve())
        priv_path.relative_to(key_dir.resolve())
    except ValueError:
        return None, None
    return pub_path, priv_path


# Env var carrying an externally-managed Ed25519 audit-signing PRIVATE key
# (raw 32-byte key, hex or base64). When set, the key is the active signer and
# is held in memory only -- never written to the local key dir -- so the audit
# chain's trust anchor can live in a KMS / HSM / secrets manager and be injected
# at deploy time rather than generated-and-left on local disk. See
# ``_injected_keypair`` and the module docstring (H29 / enterprise key custody).
_SIGNING_KEY_ENV = "MAVERICK_AUDIT_SIGNING_KEY"
_INJECTED_KEYPAIR_UNREAD = object()
_INJECTED_KEYPAIR_CACHE: tuple[bytes, bytes, str] | None | object = (
    _INJECTED_KEYPAIR_UNREAD
)


def _injected_marker_for_id(key_id: str) -> Path | None:
    """Path of the ``.injected`` marker for ``key_id`` (or None if invalid).

    The marker is a non-secret, empty file written next to the public key when
    an env-injected key is provisioned. It lets local ``verify_chain`` trust the
    lone ``<id>.pub`` (whose private ``.key`` is deliberately absent), exactly as
    a real ``.key`` sibling would -- both rest on the same assumption that the
    key dir is access-controlled (for third-party tamper-evidence, pass the
    trusted ``pubkey_hex`` explicitly regardless).
    """
    if not _is_valid_key_id(key_id):
        return None
    key_dir = _key_dir()
    marker = (key_dir / f"{key_id}.injected").resolve()
    try:
        marker.relative_to(key_dir.resolve())
    except ValueError:
        return None
    return marker


def _decode_injected_key(raw: str) -> bytes | None:
    """Decode a raw 32-byte Ed25519 private key from hex or base64.

    Returns the 32 key bytes, or None if the value isn't a valid encoding of a
    32-byte key (so a malformed env value falls back to the on-disk key path
    rather than crashing the audit writer).
    """
    import base64
    import binascii

    s = raw.strip()
    if not s:
        return None
    # Hex first (64 chars, unambiguous); then base64 (std or urlsafe).
    try:
        b = bytes.fromhex(s)
        if len(b) == 32:
            return b
    except ValueError:
        pass
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            b = decoder(s + "=" * (-len(s) % 4))
            if len(b) == 32:
                return b
        except (binascii.Error, ValueError):
            continue
    return None


def _injected_keypair() -> tuple[bytes, bytes, str] | None:
    """Return (priv, pub, key_id) for an env-injected signing key, or None.

    Consumes :data:`_SIGNING_KEY_ENV` once, removes it from ``os.environ`` as
    early as possible, and caches only decoded key material. This keeps local
    shell tools from recovering the secret from the parent process environment
    via same-user ``/proc`` reads; inherited startup environments are not an
    HSM/KMS boundary. The caller writes just the public key (+ an ``.injected``
    marker) so verification still trusts the chain without the secret ever
    touching local disk. A malformed value logs a warning and returns None
    (fall back to disk keys).
    """
    global _INJECTED_KEYPAIR_CACHE
    if _INJECTED_KEYPAIR_CACHE is not _INJECTED_KEYPAIR_UNREAD:
        return _INJECTED_KEYPAIR_CACHE

    raw = os.environ.pop(_SIGNING_KEY_ENV, None)
    if not raw:
        _INJECTED_KEYPAIR_CACHE = None
        return None
    if not _have_crypto():
        _INJECTED_KEYPAIR_CACHE = None
        return None
    priv_bytes = _decode_injected_key(raw)
    if priv_bytes is None:
        log.warning(
            "%s is set but is not a valid hex/base64 32-byte Ed25519 key; "
            "falling back to the on-disk audit signing key",
            _SIGNING_KEY_ENV,
        )
        _INJECTED_KEYPAIR_CACHE = None
        return None
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    priv = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_id = hashlib.sha256(pub_bytes).hexdigest()[:16]
    _INJECTED_KEYPAIR_CACHE = (priv_bytes, pub_bytes, key_id)
    return _INJECTED_KEYPAIR_CACHE


def _provision_injected_pubkey(pub: bytes, key_id: str) -> None:
    """Persist the PUBLIC half (+ ``.injected`` marker) of an injected key.

    Writes ``<key_id>.pub`` (world-readable) and an empty ``<key_id>.injected``
    marker so local ``verify_chain`` trusts rows signed by the injected key,
    while the private key stays out of the filesystem entirely. Best-effort and
    idempotent: a read-only key dir (e.g. a locked-down container) is tolerated
    -- signing still works from the in-memory key; only same-host local-trust
    verification needs the on-disk pub.
    """
    try:
        key_dir = _key_dir()
        key_dir.mkdir(parents=True, exist_ok=True)
        pub_path = key_dir / f"{key_id}.pub"
        if not pub_path.exists():
            pub_path.write_bytes(pub)
            try:
                os.chmod(pub_path, 0o644)
            except OSError:
                pass
        marker = key_dir / f"{key_id}.injected"
        if not marker.exists():
            marker.write_bytes(b"")
    except OSError:
        # Never let key-dir provisioning failure break audit signing.
        log.debug("could not persist injected audit pubkey for %s", key_id)


@dataclass
class ChainBreak:
    line_no: int  # 1-indexed
    # 'bad_hash' | 'bad_signature' | 'chain_mismatch' | 'malformed' | 'unsigned'
    # 'unsigned' = the row carries NONE of hash/sig/key_id, i.e. it was written
    # with audit signing disabled (the default) — distinct from 'malformed'
    # (some-but-not-all fields: the vocabulary of real tampering).
    reason: str
    detail: str


def _have_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401

        return True
    except ImportError:
        return False


def verify_ed25519(pubkey_hex: str, sig_hex: str, message: bytes) -> bool:
    """Return True iff ``sig_hex`` is a valid Ed25519 signature over
    ``message`` under ``pubkey_hex`` (both hex-encoded raw keys/sigs).

    Returns False on any verification failure or malformed input. Raises
    ImportError if ``cryptography`` is not installed -- callers that want
    fail-open behavior must guard with ``_have_crypto()`` first.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import ed25519

    try:
        pub = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))
        pub.verify(bytes.fromhex(sig_hex), message)
        return True
    except (InvalidSignature, ValueError):
        return False


def _generate_keypair() -> tuple[bytes, bytes, str]:
    """Return (private_key_bytes, public_key_bytes, key_id)."""
    if not _have_crypto():
        raise ImportError(
            "cryptography not installed. Run: pip install 'maverick-agent[audit-signing]'"
        )
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_id = hashlib.sha256(pub_bytes).hexdigest()[:16]
    return priv_bytes, pub_bytes, key_id


def _save_keypair(priv: bytes, pub: bytes, key_id: str) -> Path:
    key_dir = _key_dir()
    key_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(key_dir, 0o700)
    except OSError:
        pass
    priv_path = key_dir / f"{key_id}.key"
    pub_path = key_dir / f"{key_id}.pub"
    # Create the private signing key (the audit chain's trust anchor) with the
    # mode set AT creation. write_bytes() + a later chmod left a world-readable
    # window during which another local user could read -- and then forge with
    # -- the key. The dir chmod above is best-effort and may not apply.
    fd = os.open(str(priv_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, priv)
    finally:
        os.close(fd)
    pub_path.write_bytes(pub)
    try:
        os.chmod(priv_path, 0o600)
        os.chmod(pub_path, 0o644)
    except OSError:
        pass
    return priv_path


def rotate_audit_keypair() -> str:
    """Mint a fresh Ed25519 signing keypair and make it the active signer.

    Safe and additive: the new key becomes active because it is the most-recent
    ``.key`` (see :func:`_load_or_create_keypair`), while every prior ``<id>.pub``
    is retained so ``verify_chain`` still validates rows signed under old keys
    (each row carries its ``key_id``). No existing audit data is rewritten.

    Returns the new ``key_id``. Takes effect for new :class:`AuditSigner`
    instances (next day-file / process restart); a long-running signer keeps its
    in-memory key until restarted.
    """
    priv, pub, key_id = _generate_keypair()
    _save_keypair(priv, pub, key_id)
    return key_id


_KMS_WRAPPED_KEY_ENV = "MAVERICK_AUDIT_SIGNING_KEY_WRAPPED"


def require_offhost_signing() -> bool:
    """Whether the audit signing key MUST live off-host (KMS / injected), so the
    on-disk generated-and-left key is refused.

    On by default under enterprise mode -- the audit chain is the tamper-evidence
    a regulator relies on, and a same-host on-disk private key lets a local root
    rewrite history and re-sign it. Also flips on via ``[audit]
    require_offhost_key`` / ``MAVERICK_AUDIT_REQUIRE_OFFHOST_KEY``. Off by default
    otherwise (the local-key happy path is unchanged)."""
    env = os.environ.get("MAVERICK_AUDIT_REQUIRE_OFFHOST_KEY", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    try:
        from ..config import load_config
        val = ((load_config() or {}).get("audit") or {}).get("require_offhost_key")
        if val is not None:
            return bool(val) if not isinstance(val, str) else val.strip().lower() in {
                "1", "true", "yes", "on"}
    # failure-policy: best_effort
    except Exception:  # pragma: no cover -- config never weakens posture silently
        pass
    try:
        from ..enterprise import enterprise_enabled
        return bool(enterprise_enabled())
    # failure-policy: best_effort
    except Exception:  # pragma: no cover
        return False


def _kms_wrapped_keypair() -> tuple[bytes, bytes, str] | None:
    """Source the signing key from a KMS-wrapped blob, unwrapped into memory.

    ``MAVERICK_AUDIT_SIGNING_KEY_WRAPPED`` (hex/base64 of a KMS-wrapped 32-byte
    Ed25519 private key) + a configured cloud KMS (``[encryption.kms]`` AWS / GCP
    / Vault) lets the audit signer's private key live in KMS custody and be
    unwrapped only into process memory at startup -- never written to local disk.
    Returns ``(priv, pub, key_id)`` or ``None`` (no config / crypto absent / any
    error -> fall through to the next key source)."""
    raw = os.environ.get(_KMS_WRAPPED_KEY_ENV)
    if not raw or not _have_crypto():
        return None
    import base64
    import binascii
    s = raw.strip()
    wrapped: bytes | None = None
    try:
        wrapped = bytes.fromhex(s)
    except ValueError:
        try:
            wrapped = base64.b64decode(s, validate=True)
        except (binascii.Error, ValueError):
            wrapped = None
    if not wrapped:
        log.warning("%s is set but is not valid hex/base64; ignoring", _KMS_WRAPPED_KEY_ENV)
        return None
    try:
        from ..config import load_config
        from ..kms_backends import build_cloud_kms
        provider = str(((load_config() or {}).get("kms") or {}).get("provider") or "").strip()
        kek = build_cloud_kms(provider)
        priv_bytes = kek.unwrap(wrapped, context=b"maverick-audit-signing")
    # failure-policy: fail_soft_with_audit
    except Exception as e:
        log.warning("audit signing KMS unwrap failed (%s); falling back", e)
        return None
    if len(priv_bytes) != 32:
        log.warning("KMS-unwrapped audit key is %d bytes, expected 32; ignoring",
                    len(priv_bytes))
        return None
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    key_id = hashlib.sha256(pub_bytes).hexdigest()[:16]
    return priv_bytes, pub_bytes, key_id


def _load_or_create_keypair() -> tuple[bytes, bytes, str]:
    """Load the most-recent keypair or generate one if none exists.

    Key-source precedence: an env-injected key (:func:`_injected_keypair`) >
    a KMS-wrapped key (:func:`_kms_wrapped_keypair`) > the on-disk key. The first
    two keep the private key off local disk (only the public half is persisted,
    for verification) so the audit chain's trust anchor can live in a KMS / HSM /
    secrets manager. When :func:`require_offhost_signing` is on (enterprise mode)
    and neither off-host source is available, this RAISES rather than generate a
    same-host on-disk key a local root could use to rewrite + re-sign history.
    """
    injected = _injected_keypair()
    if injected is not None:
        priv, pub, key_id = injected
        _provision_injected_pubkey(pub, key_id)
        return priv, pub, key_id

    kms = _kms_wrapped_keypair()
    if kms is not None:
        priv, pub, key_id = kms
        _provision_injected_pubkey(pub, key_id)
        return priv, pub, key_id

    if require_offhost_signing():
        raise OffHostSigningRequiredError(
            "off-host audit signing is required (enterprise mode / [audit] "
            "require_offhost_key) but no off-host key is configured. Set "
            f"{_SIGNING_KEY_ENV} (a KMS/secrets-manager-sourced Ed25519 key) or "
            f"{_KMS_WRAPPED_KEY_ENV} (a KMS-wrapped key) so the audit signing key "
            "never lives generated-and-left on the local host."
        )

    key_dir = _key_dir()
    if key_dir.exists():
        priv_files = sorted(key_dir.glob("*.key"))
        if priv_files:
            latest = max(priv_files, key=lambda p: p.stat().st_mtime)
            key_id = latest.stem
            pub_path = key_dir / f"{key_id}.pub"
            if pub_path.exists():
                return latest.read_bytes(), pub_path.read_bytes(), key_id
    priv, pub, key_id = _generate_keypair()
    _save_keypair(priv, pub, key_id)
    return priv, pub, key_id


class AuditSigner:
    """Sign + chain audit log lines.

    Wraps an NDJSON sink, adding ``prev_hash`` / ``hash`` / ``sig`` /
    ``key_id`` fields to each row before writing.

    Thread-safe. A single AuditSigner per file is assumed; cross-
    process concurrency would need an external lock (we don't bake
    that in to avoid adding flock/fcntl complexity for the common
    single-process case).
    """

    def __init__(self, audit_path: Path):
        self._lock = threading.Lock()
        self._path = audit_path
        self._priv_bytes, self._pub_bytes, self._key_id = _load_or_create_keypair()
        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519
        except ImportError as e:
            raise ImportError(
                "cryptography not installed. Run: pip install 'maverick-agent[audit-signing]'"
            ) from e
        self._signer = ed25519.Ed25519PrivateKey.from_private_bytes(self._priv_bytes)
        self._last_hash = self._resume_last_hash()

    def _resume_last_hash(self) -> str:
        """If the file has prior entries, find the latest hash to chain on.

        A torn final line (crash mid-write, no trailing newline) must NOT
        silently reset the chain to genesis (prev_hash=""), which would let
        an attacker truncate-and-reappend a self-consistent sub-chain that
        verifies clean. If the last non-empty line is unparseable, raise so
        the caller surfaces it instead of starting a fresh chain.
        """
        if not self._path.exists() or self._path.stat().st_size == 0:
            return ""
        with open(self._path, "rb") as f:
            last_line = b""
            for line in f:
                if line.strip():
                    last_line = line
        if not last_line:
            return ""
        try:
            data = json.loads(last_line)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"audit chain resume: last line of {self._path} is unparseable "
                "(torn write?); refusing to silently restart the chain"
            ) from e
        return str(data.get("hash") or "")

    def write(self, event: dict) -> bool:
        """Append a signed + chained event row. Returns True on success."""
        with self._lock:
            payload = dict(event)
            payload["prev_hash"] = self._last_hash
            payload["key_id"] = self._key_id
            row_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
            row_hash = hashlib.sha256(row_bytes).hexdigest()
            sig = self._signer.sign(bytes.fromhex(row_hash)).hex()
            payload["hash"] = row_hash
            payload["sig"] = sig
            line = json.dumps(payload, default=str) + "\n"
            try:
                from .writer import _file_append_lock

                self._path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._path, "a", encoding="utf-8") as f:
                    # Cross-process advisory lock: serialize concurrent writers
                    # so an append above PIPE_BUF can't interleave a torn row
                    # into the signed chain. POSIX-only; no-op elsewhere.
                    with _file_append_lock(f):
                        f.write(line)
                        # fsync so a power loss can't lose committed audit rows
                        # (or leave a torn line that breaks chain resume). The
                        # audit log is the trust anchor; durability matters more
                        # than the small write cost here.
                        f.flush()
                        os.fsync(f.fileno())
                try:
                    os.chmod(self._path, 0o600)
                except OSError:
                    pass
                # Only advance the in-memory chain head AFTER the row is
                # durably on disk; otherwise a crash between write and this
                # line would chain the next row on a hash that isn't there.
                self._last_hash = row_hash
                return True
            except OSError as e:
                log.warning("audit signer: write failed: %s", e)
                return False

    @property
    def public_key_hex(self) -> str:
        return self._pub_bytes.hex()


def _segment_text(path: Path) -> str:
    """A day-file's NDJSON text, transparently decrypting an at-rest-sealed segment
    so the verifier works on sealed and plaintext day-files alike.

    Unlike export readers, verification must fail closed: an unreadable or
    undecryptable segment is signed evidence that cannot be proven intact.
    """
    from .sealing import segment_text
    return segment_text(path, fail_soft=False)


def verify_chain(path: Path, pubkey_hex: str | None = None) -> list[ChainBreak]:
    """Walk every line; verify chain links + signatures.

    If ``pubkey_hex`` is None, the verifier looks up each row's
    ``key_id`` against ~/.maverick/audit/keys/<keyid>.pub.

    Returns a list of breaks. Empty list = chain intact.
    """
    if not _have_crypto():
        return [ChainBreak(0, "no_crypto", "cryptography not installed")]
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import ed25519

    breaks: list[ChainBreak] = []
    if not path.exists():
        return [ChainBreak(0, "missing_file", str(path))]
    prev = ""
    pubkey_cache: dict[str, ed25519.Ed25519PublicKey] = {}

    def _load_pubkey(key_id: str):
        if key_id in pubkey_cache:
            return pubkey_cache[key_id]
        if pubkey_hex:
            obj = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))
        else:
            # Trust a local .pub only when its private .key sibling also exists
            # — i.e. this host actually generated that keypair — OR when an
            # ``.injected`` marker is present (the key was provisioned out of
            # band from a KMS/secret-manager, so the private half is
            # deliberately absent from disk). That closes the "attacker drops a
            # lone forged <id>.pub and re-signs rows" vector while still honoring
            # key rotation (writes .key+.pub) and env-injected keys (write
            # .pub+.injected). Both rest on the key dir being access-controlled;
            # for third-party tamper-evidence, callers should pass the trusted
            # pubkey_hex explicitly.
            pub_path, priv_path = _key_paths_for_id(key_id)
            if pub_path is None or not pub_path.exists():
                return None
            marker = _injected_marker_for_id(key_id)
            if not priv_path.exists() and (marker is None or not marker.exists()):
                return None
            obj = ed25519.Ed25519PublicKey.from_public_bytes(pub_path.read_bytes())
        pubkey_cache[key_id] = obj
        return obj

    try:
        text = _segment_text(path)
    # failure-policy: fail_closed
    except Exception as e:
        return [ChainBreak(0, "unreadable_segment", str(e))]

    with io.StringIO(text) as f:
        for n, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                breaks.append(ChainBreak(n, "malformed", str(e)))
                continue
            row_hash = data.get("hash")
            sig = data.get("sig")
            row_prev = data.get("prev_hash", "")
            key_id = data.get("key_id", "")
            if not row_hash and not sig and not key_id:
                if pubkey_hex or row_prev:
                    # A trusted pubkey means the caller expected signed rows;
                    # an orphaned prev_hash means signing-only chain context is
                    # still present. In either case, all signature fields being
                    # absent is suspicious (for example, stripped signatures),
                    # not an honestly unsigned deployment.
                    breaks.append(ChainBreak(
                        n, "malformed",
                        "missing hash/sig/key_id (possible stripped signature fields)",
                    ))
                else:
                    # Written with signing disabled (the opt-in default). Not
                    # the same vocabulary as tampering: a verifier in a default
                    # deployment must be able to say "signing was never on".
                    breaks.append(ChainBreak(
                        n, "unsigned",
                        "row has no hash/sig/key_id (audit signing disabled)",
                    ))
                continue
            if not row_hash or not sig or not key_id:
                breaks.append(ChainBreak(n, "malformed", "missing hash/sig/key_id"))
                continue
            if row_prev != prev:
                breaks.append(
                    ChainBreak(
                        n,
                        "chain_mismatch",
                        f"row prev={row_prev[:12]}... expected {prev[:12] or '(empty)'}",
                    )
                )
            payload_for_hash = {k: v for k, v in data.items() if k not in ("hash", "sig")}
            expected_hash = hashlib.sha256(
                json.dumps(payload_for_hash, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            if expected_hash != row_hash:
                breaks.append(ChainBreak(n, "bad_hash", "content rehash != row hash"))
            pub = _load_pubkey(key_id)
            if pub is None:
                breaks.append(ChainBreak(n, "no_pubkey", f"key_id {key_id!r}"))
            else:
                try:
                    pub.verify(bytes.fromhex(sig), bytes.fromhex(row_hash))
                except InvalidSignature:
                    breaks.append(ChainBreak(n, "bad_signature", "Ed25519 verify failed"))
                except ValueError as e:
                    # A tampered sig/hash that isn't valid hex must be
                    # flagged as a break, NOT crash the verifier (which
                    # would skip every later row — the opposite of what
                    # a tamper-evidence tool should do).
                    breaks.append(ChainBreak(n, "bad_signature", f"malformed sig/hash: {e}"))
            prev = row_hash
    return breaks


# ---- cross-file tip-ledger (#462/#443) -------------------------------------

def _file_tip_and_count(path: Path) -> tuple[str, int]:
    """Return ``(last_row_hash, non_empty_row_count)`` for a signed day-file."""
    tip = ""
    count = 0
    with io.StringIO(_segment_text(path)) as f:
        for line in f:
            if not line.strip():
                continue
            count += 1
            try:
                tip = str(json.loads(line).get("hash") or tip)
            except json.JSONDecodeError:
                pass
    return tip, count


def day_files(audit_dir: Path) -> list[Path]:
    """Date-named day-files (YYYY-MM-DD.ndjson), excluding the anchor ledger.

    The single definition of "what counts as an audit day-file"; the read-side
    consumers (export / dsar / soc2) reach it via :mod:`maverick.audit.reader`.
    """
    return sorted(
        p for p in audit_dir.glob("*.ndjson") if _DAY_RE.fullmatch(p.stem)
    )


def _anchored_days(audit_dir: Path) -> set[str]:
    path = audit_dir / ANCHOR_FILENAME
    days: set[str] = set()
    if not path.exists():
        return days
    with io.StringIO(_segment_text(path)) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("kind") == "anchor" and d.get("day"):
                days.add(str(d["day"]))
    return days


def _anchor_marker_path(audit_dir: Path) -> Path:
    """Return the durable marker that records an expected anchor ledger.

    The marker prevents a deleted ``anchors.ndjson`` from being silently
    recreated from only the day-files that an attacker chose to leave behind.
    """
    return audit_dir / ANCHOR_MARKER_FILENAME


def _mark_anchor_ledger_required(audit_dir: Path) -> None:
    marker = _anchor_marker_path(audit_dir)
    if marker.exists():
        return
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            "anchors.ndjson is required for audit tamper-evidence\n",
            encoding="utf-8",
        )
    except OSError as e:  # pragma: no cover - best-effort marker
        log.warning("audit anchors: failed to write ledger marker: %s", e)


def _ensure_anchor_ledger(audit_dir: Path) -> bool:
    """Return whether it is safe to append to the anchor ledger.

    A missing ledger is acceptable before the first completed day is anchored.
    Once the marker records that the ledger has existed, however, a missing
    ledger is suspicious and must not be rebuilt from only the remaining
    day-files.
    """
    anchor_path = audit_dir / ANCHOR_FILENAME
    if anchor_path.exists():
        _mark_anchor_ledger_required(audit_dir)
        return True
    return not _anchor_marker_path(audit_dir).exists()


def _append_anchor(audit_dir: Path, day: str, tip_hash: str, row_count: int) -> bool:
    """Append one signed, chained anchor row to the tip-ledger."""
    if not _have_crypto():
        return False
    signer = AuditSigner(audit_dir / ANCHOR_FILENAME)
    ok = bool(
        signer.write({
            "kind": "anchor",
            "day": day,
            "tip_hash": tip_hash,
            "row_count": row_count,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
    )
    if ok:
        _mark_anchor_ledger_required(audit_dir)
    return ok


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def ensure_anchors(audit_dir: Path) -> int:
    """Record a tip-ledger anchor for every COMPLETED day-file lacking one.

    Only completed days (< today, UTC) are anchored -- today's file is still
    growing. Already-anchored days are left alone: we never silently re-anchor
    over a tampered file (that's ``verify_anchors``' job to flag); a legitimate
    GDPR erase re-anchors its day explicitly via ``reanchor_day_after_erase``.
    Returns the number of anchors written.
    """
    if not _have_crypto():
        return 0
    if not _ensure_anchor_ledger(audit_dir):
        log.warning(
            "audit anchors: %s is missing but was previously required; refusing to rebuild",
            ANCHOR_FILENAME,
        )
        return 0
    today = _today_utc()
    anchored = _anchored_days(audit_dir)
    written = 0
    for day_file in day_files(audit_dir):
        day = day_file.stem
        if day >= today or day in anchored:
            continue
        tip, count = _file_tip_and_count(day_file)
        if count and _append_anchor(audit_dir, day, tip, count):
            written += 1
    return written


def reanchor_day_after_erase(audit_dir: Path, day_file: Path) -> None:
    """After a GDPR erase rewrites a completed day-file (changing its tip),
    append a fresh superseding anchor so ``verify_anchors`` matches the new
    state. The prior anchor stays in the append-only ledger -- an auditable
    record that the day was modified."""
    if not _have_crypto():
        return
    day = day_file.stem
    if not _DAY_RE.fullmatch(day) or day >= _today_utc():
        return  # not a completed day-file
    tip, count = _file_tip_and_count(day_file)
    if count:
        _append_anchor(audit_dir, day, tip, count)


def verify_anchors(audit_dir: Path, pubkey_hex: str | None = None) -> list[ChainBreak]:
    """Cross-file tamper-evidence: confirm every anchored day-file still exists
    and matches its latest recorded tip hash + row count. Catches deletion or
    truncation of a whole day-file, which per-file ``verify_chain`` cannot.

    Verifies the anchor ledger's own signed chain first, then each day.
    Empty list = intact.
    """
    anchor_path = audit_dir / ANCHOR_FILENAME
    if not anchor_path.exists():
        has_completed_days = any(p.stem < _today_utc() for p in day_files(audit_dir))
        if has_completed_days or _anchor_marker_path(audit_dir).exists():
            return [
                ChainBreak(
                    0,
                    "anchor_ledger_missing",
                    f"{ANCHOR_FILENAME} is missing; "
                    "cross-file audit tamper-evidence cannot be verified",
                )
            ]
        return []
    breaks = list(verify_chain(anchor_path, pubkey_hex))
    # The ledger is append-only; the last anchor for a day wins (supersession).
    latest: dict[str, dict] = {}
    with open(anchor_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("kind") == "anchor" and d.get("day"):
                latest[str(d["day"])] = d
    for day, anc in sorted(latest.items()):
        day_file = audit_dir / f"{day}.ndjson"
        if not day_file.exists():
            breaks.append(ChainBreak(
                0, "anchored_file_deleted", f"{day}.ndjson is anchored but missing"))
            continue
        try:
            tip, count = _file_tip_and_count(day_file)
        # failure-policy: fail_closed
        except Exception as e:
            breaks.append(ChainBreak(
                0, "unreadable_segment", f"{day}: {e}"))
            continue
        if tip != anc.get("tip_hash"):
            breaks.append(ChainBreak(
                0, "anchor_tip_mismatch",
                f"{day}: tip {tip[:12]}... != anchored {str(anc.get('tip_hash'))[:12]}..."))
        if count != anc.get("row_count"):
            breaks.append(ChainBreak(
                0, "anchor_count_mismatch",
                f"{day}: {count} rows != anchored {anc.get('row_count')}"))
    return breaks


def reanchor_file(path: Path, *, force: bool = False, preverified: bool = False) -> int:
    """Re-chain + re-sign every row of a signed audit file, in place.

    A GDPR erase tombstones or removes rows but does NOT recompute the
    ``prev_hash``/``hash``/``sig`` chain, so ``verify_chain()`` then reports
    breaks that are indistinguishable from tampering. This rewrites the file,
    recomputing each row's chain fields under the current key so the chain
    verifies clean again, preserving row content and order. The caller writes
    a signed ``erase`` marker first so a verifier holding the trusted pubkey
    can see the cut was authorized.

    By default, re-anchoring first verifies the existing file and refuses to
    rewrite a broken chain. Callers that just performed an authorized erase
    may pass ``preverified=True`` only after verifying the original file before
    mutating it; this prevents a routine erase from laundering older tampering.

    ``force`` re-signs even rows that currently carry no signature (e.g. a
    file whose every signed row was tombstoned by the erase). Without it, a
    file with no signed rows is left untouched (returns -1) -- erasing an
    unsigned log has no chain to repair.

    Returns rows re-signed, 0 if no rewrite was needed (already consistent),
    or -1 if skipped (crypto unavailable, missing file, or unsigned without
    ``force``).

    Re-anchoring re-signs under the host key: it makes *authorized* erasure
    verifiable-clean. It is not extra protection against an attacker who
    already holds that key -- that is inherent to same-host key storage.
    """
    if not _have_crypto():
        return -1
    if not path.exists() or path.is_dir():
        return -1
    from cryptography.hazmat.primitives.asymmetric import ed25519

    try:
        raw = path.read_bytes()
    except OSError:
        return -1
    # A closed day-file may be at-rest *sealed* (#1015). Re-chain its decrypted
    # NDJSON, but remember the sealed state so the rewrite below writes it back
    # sealed -- a re-anchor (e.g. after a GDPR erase) must not silently unseal a
    # confidential segment to plaintext.
    from ..crypto_at_rest import is_sealed
    was_sealed = is_sealed(raw)
    original = _segment_text(path)

    parsed: list[tuple[str, object]] = []
    any_signed = False
    for raw in original.splitlines():
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Never drop data on a rewrite: preserve unparseable lines
            # verbatim (and out of the chain), mirroring verify_chain.
            parsed.append(("raw", raw))
            continue
        if data.get("sig") and data.get("hash") and data.get("key_id"):
            any_signed = True
        parsed.append(("json", data))

    if not any_signed and not force:
        return -1
    if not preverified:
        breaks = verify_chain(path)
        if breaks:
            log.warning(
                "audit reanchor: refusing to rewrite %s; chain is not clean (%s)",
                path,
                breaks[0],
            )
            return -1

    priv_bytes, _pub, key_id = _load_or_create_keypair()
    signer = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)

    out_lines: list[str] = []
    prev = ""
    resigned = 0
    for kind, val in parsed:
        if kind == "raw":
            out_lines.append(val)  # type: ignore[arg-type]
            continue
        assert isinstance(val, dict)
        # Strip the old chain fields, then rebuild them exactly as
        # AuditSigner.write does (hash over payload incl. prev_hash + key_id,
        # sort_keys=True; sig over the hash bytes).
        payload = {k: v for k, v in val.items() if k not in ("hash", "sig", "prev_hash", "key_id")}
        payload["prev_hash"] = prev
        payload["key_id"] = key_id
        row_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        payload["hash"] = row_hash
        payload["sig"] = signer.sign(bytes.fromhex(row_hash)).hex()
        out_lines.append(json.dumps(payload, default=str))
        prev = row_hash
        resigned += 1

    new_content = "".join(line + "\n" for line in out_lines)
    if new_content == original:
        return 0  # untouched rows under an unchanged key -> no rewrite

    from .sealing import encode_segment
    new_bytes = encode_segment(new_content, sealed=was_sealed)

    tmp = path.with_suffix(".ndjson.reanchortmp")
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o600
    try:
        with open(tmp, "wb") as f:
            f.write(new_bytes)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    except OSError as e:
        log.warning("audit reanchor: %s: %s", path, e)
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        return -1
    return resigned


__all__ = [
    "AuditSigner",
    "verify_chain",
    "verify_ed25519",
    "ChainBreak",
    "KEY_DIR",
    "reanchor_file",
    "rotate_audit_keypair",
]
