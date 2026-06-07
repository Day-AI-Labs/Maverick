"""AES-256-GCM encryption at rest for Maverick's sensitive local stores.

The kernel keeps its state in plaintext on disk by default (the world model, the
audit log, and the cross-session memory directory). That is fine for a personal
agent but is a GDPR Art. 32 / HIPAA exposure the moment the agent handles
sensitive data: anyone who can read ``~/.maverick`` sees everything.

This module provides authenticated at-rest encryption for bytes/text plus key
management that reuses the local-keyfile pattern of the audit signer. It is
**opt-in**: enable it with ``[encryption] at_rest = true`` /
``MAVERICK_ENCRYPT_AT_REST=1``, and it is **implied by enterprise mode** (handling
sensitive data -> seal it at rest). Off by default -> behaviour is unchanged.

Key resolution (first match wins):
  1. ``MAVERICK_ENCRYPTION_KEY`` — a 32-byte key as hex or base64, so an operator
     can inject a KMS-derived key without it ever touching disk.
  2. ``~/.maverick/keys/at_rest.key`` — generated on first use, ``chmod 600``.

Sealed blobs carry a magic header (:data:`_MAGIC`), so :func:`unseal` transparently
returns plaintext written *before* encryption was enabled — a gradual migration
with no flag-day re-encrypt.

Coverage (what is actually sealed today):
  - the cross-session **memory** store (files), and
  - the **world-DB content columns** sealed via ``encryption_migrate._SEALED_COLUMNS``
    — facts, conversation turns/messages, open questions, and goal content
    (titles/descriptions/results) + per-agent goal events.
  The **audit log is NOT encrypted at rest** — it is *signed* for tamper-evidence
  (see ``audit/signing.py``), which is integrity, not confidentiality. Treat audit
  confidentiality as out of scope here until that is wired in.

By default a sealed column read back unsealed (legacy/pre-migration) is passed
through; :func:`strict_at_rest` makes that an integrity failure instead.
"""
from __future__ import annotations

import base64
import binascii
import os
import secrets
import stat
from pathlib import Path

_MAGIC = b"MVKAR1\n"          # versioned header: Maverick At-Rest v1
_NONCE_BYTES = 12
_KEY_BYTES = 32              # AES-256
_KEY_PATH = Path.home() / ".maverick" / "keys" / "at_rest.key"


class EncryptionUnavailable(RuntimeError):
    """At-rest encryption was requested but cannot be performed (missing crypto
    or an unreadable/invalid key). Callers fail closed rather than write plaintext."""


def _have_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        return True
    except ImportError:
        return False


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def at_rest_enabled() -> bool:
    """Opt-in. ``MAVERICK_ENCRYPT_AT_REST`` env (a falsey value force-disables)
    wins over ``[encryption] at_rest`` in config, which wins over enterprise mode.
    Off by default."""
    env = os.environ.get("MAVERICK_ENCRYPT_AT_REST")
    if env is not None and env.strip() != "":
        return _truthy(env)
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("encryption") or {}
    except Exception:
        cfg = {}
    if "at_rest" in cfg:
        v = cfg.get("at_rest")
        return _truthy(v) if isinstance(v, str) else bool(v)
    # Enterprise mode implies at-rest encryption (sensitive data stays sealed).
    try:
        from .enterprise import enterprise_enabled
        return enterprise_enabled()
    except Exception:
        return False


def strict_at_rest() -> bool:
    """Opt-in strict read mode (default off). When on -- and at-rest is enabled --
    a value read back from a *sealed column* that is NOT sealed is treated as an
    integrity failure (withheld) instead of trusted as plaintext.

    Enable it only AFTER ``maverick encryption migrate`` has sealed legacy rows:
    before migration, pre-existing plaintext in those columns is expected, and
    strict mode would (correctly) withhold it. ``MAVERICK_ENCRYPT_STRICT`` env wins
    over ``[encryption] strict``."""
    env = os.environ.get("MAVERICK_ENCRYPT_STRICT")
    if env is not None and env.strip() != "":
        return _truthy(env)
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("encryption") or {}
    except Exception:
        return False
    v = cfg.get("strict")
    return _truthy(v) if isinstance(v, str) else bool(v)


def _decode_injected_key(raw: str) -> bytes:
    raw = raw.strip()
    if len(raw) == _KEY_BYTES * 2:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    try:
        return base64.b64decode(raw, validate=True)
    except Exception as e:  # noqa: BLE001
        raise EncryptionUnavailable(
            "MAVERICK_ENCRYPTION_KEY is not valid hex or base64"
        ) from e


def _secure_key_dir() -> None:
    """Ensure the on-disk key directory is private before touching key material."""
    try:
        _KEY_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(_KEY_PATH.parent, 0o700)
    except OSError as e:
        raise EncryptionUnavailable(
            f"cannot secure at-rest key directory {_KEY_PATH.parent}: {e}"
        ) from e


def _ensure_private_key_file() -> None:
    """Tighten existing key-file permissions before loading it."""
    try:
        st = _KEY_PATH.stat()
    except OSError as e:
        raise EncryptionUnavailable(f"cannot stat at-rest key {_KEY_PATH}: {e}") from e
    if not stat.S_ISREG(st.st_mode):
        raise EncryptionUnavailable(f"at-rest key {_KEY_PATH} is not a regular file")
    if st.st_mode & 0o077:
        try:
            os.chmod(_KEY_PATH, 0o600)
        except OSError as e:
            raise EncryptionUnavailable(
                f"cannot secure at-rest key {_KEY_PATH}: {e}"
            ) from e


def _read_key_file() -> bytes:
    _secure_key_dir()
    _ensure_private_key_file()
    try:
        key = bytes.fromhex(_KEY_PATH.read_text().strip())
    except (OSError, ValueError) as e:
        raise EncryptionUnavailable(f"cannot read at-rest key {_KEY_PATH}: {e}") from e
    if len(key) != _KEY_BYTES:
        raise EncryptionUnavailable(f"at-rest key {_KEY_PATH} is malformed")
    return key


def _write_new_key_file(key: bytes) -> None:
    _secure_key_dir()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(_KEY_PATH, flags, 0o600)
    except FileExistsError:
        raise
    except OSError as e:
        raise EncryptionUnavailable(f"cannot write at-rest key {_KEY_PATH}: {e}") from e
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key.hex())
        os.chmod(_KEY_PATH, 0o600)
    except OSError as e:
        raise EncryptionUnavailable(f"cannot write at-rest key {_KEY_PATH}: {e}") from e


def _load_or_create_key() -> bytes:
    raw = os.environ.get("MAVERICK_ENCRYPTION_KEY")
    if raw:
        key = _decode_injected_key(raw)
        if len(key) != _KEY_BYTES:
            raise EncryptionUnavailable(
                f"MAVERICK_ENCRYPTION_KEY must decode to {_KEY_BYTES} bytes, got {len(key)}"
            )
        return key
    if _KEY_PATH.exists():
        return _read_key_file()
    # First use: generate + persist atomically with private directory/file modes.
    key = secrets.token_bytes(_KEY_BYTES)
    try:
        _write_new_key_file(key)
    except FileExistsError:
        # Another process won the first-use race; load the private key it wrote.
        return _read_key_file()
    return key


def is_sealed(blob: bytes) -> bool:
    """True if ``blob`` was produced by :func:`seal` (carries the magic header)."""
    return blob[: len(_MAGIC)] == _MAGIC


def seal(plaintext: bytes) -> bytes:
    """Encrypt with AES-256-GCM. Returns ``MAGIC || nonce || ciphertext+tag``.

    Raises :class:`EncryptionUnavailable` if crypto/key are missing (fail closed:
    the caller must not silently fall back to writing plaintext)."""
    if not _have_crypto():
        raise EncryptionUnavailable(
            "at-rest encryption enabled but 'cryptography' is not installed "
            "(pip install 'maverick-agent[audit-signing]')"
        )
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _load_or_create_key()
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return _MAGIC + nonce + ct


def unseal(blob: bytes) -> bytes:
    """Decrypt a sealed blob. A blob *without* the magic header is returned
    unchanged — plaintext written before encryption was enabled (transparent
    migration). Raises :class:`EncryptionUnavailable` only when a genuinely
    sealed blob can't be opened."""
    if not is_sealed(blob):
        return blob
    if not _have_crypto():
        raise EncryptionUnavailable(
            "found encrypted data but 'cryptography' is not installed"
        )
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _load_or_create_key()
    body = blob[len(_MAGIC):]
    nonce, ct = body[:_NONCE_BYTES], body[_NONCE_BYTES:]
    return AESGCM(key).decrypt(nonce, ct, None)


def seal_text(text: str) -> bytes:
    return seal(text.encode("utf-8"))


def unseal_to_text(blob: bytes) -> str:
    return unseal(blob).decode("utf-8", errors="replace")


# --- TEXT-column helpers ---------------------------------------------------
# Seal a string into a single TEXT-storable token so a sensitive SQLite column
# (TEXT affinity) can hold ciphertext with no schema change. A value without the
# marker is treated as legacy plaintext (transparent migration).
_STR_PREFIX = "MVKAR1:"


def is_sealed_str(s: object) -> bool:
    return isinstance(s, str) and s.startswith(_STR_PREFIX)


def seal_to_str(text: str) -> str:
    """Seal ``text`` into ``'MVKAR1:' + base64(sealed)`` -- safe for a TEXT column."""
    return _STR_PREFIX + base64.b64encode(seal(text.encode("utf-8"))).decode("ascii")


def unseal_from_str(s: str) -> str:
    """Inverse of :func:`seal_to_str`.

    Strings without the marker are returned unchanged (legacy plaintext written
    before encryption was enabled). Because the marker is public and TEXT fields
    may also contain attacker-controlled plaintext while encryption is disabled,
    a marked value is only decrypted after its payload decodes to a structurally
    valid sealed blob. Marker collisions remain plaintext; authentic-looking
    sealed blobs still fail closed if decryption/authentication fails.
    """
    if not is_sealed_str(s):
        return s
    try:
        blob = base64.b64decode(s[len(_STR_PREFIX):], validate=True)
    except (ValueError, binascii.Error):
        return s
    if not is_sealed(blob) or len(blob) < len(_MAGIC) + _NONCE_BYTES + 16:
        return s
    return unseal(blob).decode("utf-8", errors="replace")


__all__ = [
    "at_rest_enabled",
    "is_sealed",
    "is_sealed_str",
    "seal",
    "unseal",
    "seal_text",
    "unseal_to_text",
    "seal_to_str",
    "unseal_from_str",
    "EncryptionUnavailable",
]
