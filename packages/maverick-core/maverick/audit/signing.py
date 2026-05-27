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

Optional [audit-signing] extra (cryptography>=42.0).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


KEY_DIR = Path.home() / ".maverick" / "audit" / "keys"


@dataclass
class ChainBreak:
    line_no: int       # 1-indexed
    reason: str        # 'bad_hash' | 'bad_signature' | 'chain_mismatch' | 'malformed'
    detail: str


def _have_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401
        return True
    except ImportError:
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
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(KEY_DIR, 0o700)
    except OSError:
        pass
    priv_path = KEY_DIR / f"{key_id}.key"
    pub_path = KEY_DIR / f"{key_id}.pub"
    priv_path.write_bytes(priv)
    pub_path.write_bytes(pub)
    try:
        os.chmod(priv_path, 0o600)
        os.chmod(pub_path, 0o644)
    except OSError:
        pass
    return priv_path


def _load_or_create_keypair() -> tuple[bytes, bytes, str]:
    """Load the most-recent keypair or generate one if none exists."""
    if KEY_DIR.exists():
        priv_files = sorted(KEY_DIR.glob("*.key"))
        if priv_files:
            latest = max(priv_files, key=lambda p: p.stat().st_mtime)
            key_id = latest.stem
            pub_path = KEY_DIR / f"{key_id}.pub"
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
        """If the file has prior entries, find the latest hash to chain on."""
        if not self._path.exists() or self._path.stat().st_size == 0:
            return ""
        try:
            with open(self._path, "rb") as f:
                last_line = b""
                for line in f:
                    if line.strip():
                        last_line = line
            if not last_line:
                return ""
            data = json.loads(last_line)
            return str(data.get("hash") or "")
        except (OSError, json.JSONDecodeError):
            return ""

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
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line)
                try:
                    os.chmod(self._path, 0o600)
                except OSError:
                    pass
                self._last_hash = row_hash
                return True
            except OSError as e:
                log.warning("audit signer: write failed: %s", e)
                return False

    @property
    def public_key_hex(self) -> str:
        return self._pub_bytes.hex()


def verify_chain(path: Path, pubkey_hex: Optional[str] = None) -> list[ChainBreak]:
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
            p = KEY_DIR / f"{key_id}.pub"
            if not p.exists():
                return None
            obj = ed25519.Ed25519PublicKey.from_public_bytes(p.read_bytes())
        pubkey_cache[key_id] = obj
        return obj

    with open(path, encoding="utf-8") as f:
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
            if not row_hash or not sig or not key_id:
                breaks.append(ChainBreak(n, "malformed", "missing hash/sig/key_id"))
                continue
            if row_prev != prev:
                breaks.append(ChainBreak(
                    n, "chain_mismatch",
                    f"row prev={row_prev[:12]}... expected {prev[:12] or '(empty)'}",
                ))
            payload_for_hash = {
                k: v for k, v in data.items()
                if k not in ("hash", "sig")
            }
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
            prev = row_hash
    return breaks


__all__ = ["AuditSigner", "verify_chain", "ChainBreak", "KEY_DIR"]
