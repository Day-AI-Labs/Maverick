"""AES-256-GCM encryption at rest for Maverick's sensitive local stores.

The kernel keeps its state in plaintext on disk by default (the world model, the
audit log, and the cross-session memory directory). That is fine for a personal
agent but is a GDPR Art. 32 / HIPAA exposure the moment the agent handles
sensitive data: anyone who can read ``~/.maverick`` sees everything.

This module provides authenticated at-rest encryption for bytes/text plus key
management that reuses the local-keyfile pattern of the audit signer. It is
**on by default** (secure-by-default): new writes are sealed and the key
auto-generates on first use. Disable it with ``[encryption] at_rest = false`` /
``MAVERICK_ENCRYPT_AT_REST=0`` (or the whole posture via ``[security]
secure_defaults = false`` / ``MAVERICK_SECURE_DEFAULT=0``); it is also **implied
by enterprise mode** and **forced by a compliance floor** (e.g. HIPAA), which an
opt-out cannot override. Existing installs are safe to leave on -- reads are
plaintext-tolerant, so rows written before it was enabled are returned unchanged
until rewritten (``maverick encryption migrate`` seals them eagerly).

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
    — facts, conversation turns/messages, open questions, goal content
    (titles/descriptions/results) + per-agent goal events, episode
    summaries/outcomes, and parked-approval action/scope/detail.
  The audit log's **closed day-files** can be sealed via ``maverick audit seal``
  (``audit/sealing.py``); the *current* day-file stays plaintext for the live
  append + signing path, and reads/``audit verify`` decrypt sealed segments
  transparently. The log is independently *signed* for tamper-evidence
  (``audit/signing.py``) -- integrity, orthogonal to this confidentiality.

By default a sealed column read back unsealed (legacy/pre-migration) is passed
through; :func:`strict_at_rest` makes that an integrity failure instead.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
import secrets
import shutil
import stat
from pathlib import Path

from .paths import data_dir

log = logging.getLogger(__name__)

_MAGIC = b"MVKAR1\n"          # versioned header: Maverick At-Rest v1 (single key)
_MAGIC_V2 = b"MVKAR2\n"       # v2: keyring header -- MAGIC || keyid(8) || nonce || ct
# Per-tenant envelope-sealed blob header. MUST equal tenant_kms._SEAL_MAGIC (a
# test asserts this); duplicated here so is_sealed() stays cheap and we avoid a
# crypto_at_rest <-> tenant_kms import cycle (tenant_kms imports from this module).
_TENANT_MAGIC = b"MVKTEN1\n"
_NONCE_BYTES = 12
_KEY_BYTES = 32              # AES-256
_KEYID_BYTES = 8             # short key fingerprint embedded in v2 blobs
_KEY_PATH = data_dir("keys", "at_rest.key")


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
    """Opt-in unless required by an active compliance profile.

    Compliance floors are mandatory and strictest-wins: HIPAA-mode at-rest
    encryption cannot be disabled by leaving or setting the standalone
    encryption knob false. With no such floor, ``MAVERICK_ENCRYPT_AT_REST`` env
    wins over ``[encryption] at_rest`` in config, which wins over enterprise
    mode. Off by default.
    """
    try:
        from .compliance_profiles import FLOOR_ENCRYPTION_AT_REST, requires_floor
        if requires_floor(FLOOR_ENCRYPTION_AT_REST):
            return True
    except Exception:
        pass
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
    # Secure-by-default otherwise: seal new writes unless explicitly disabled.
    # Safe for existing installs -- reads are plaintext-tolerant (unseal_from_str
    # returns unmarked legacy values unchanged), so mixing sealed + plaintext
    # rows just works; the key auto-generates on first use (~/.maverick/keys).
    try:
        from .enterprise import enterprise_enabled
        if enterprise_enabled():
            return True
        from .security_defaults import secure_by_default
        return secure_by_default()
    except Exception:
        return False


def per_tenant_at_rest() -> bool:
    """Opt-in per-tenant envelope encryption (default off).

    When on **and** at-rest is enabled, new seals use the *current tenant's* own
    data key (:mod:`maverick.tenant.kms`) instead of the single process-wide key,
    so one tenant's key never opens another tenant's data — the posture a hosted
    multi-tenant store needs. Reads auto-detect by magic header, so data already
    sealed with the global key stays readable (transparent migration, no flag-day
    re-encrypt). ``MAVERICK_ENCRYPT_PER_TENANT`` env wins over ``[encryption]
    per_tenant``.

    Intended for deployments where every read/write is tenant-scoped (the seal
    is bound to ``paths.current_tenant()``); on a single-tenant box leave it off."""
    env = os.environ.get("MAVERICK_ENCRYPT_PER_TENANT")
    if env is not None and env.strip() != "":
        return _truthy(env)
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("encryption") or {}
    except Exception:
        return False
    v = cfg.get("per_tenant")
    return _truthy(v) if isinstance(v, str) else bool(v)


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
    # At-rest is on by default now, so this auto-generation happens silently on
    # most installs. The key file is the ONLY way to read sealed data -- losing it
    # loses everything sealed under it -- so make the durability requirement loud.
    log.warning(
        "at-rest encryption generated a new key at %s. This key is the only way "
        "to decrypt sealed data; if it is lost, that data is unrecoverable. Back "
        "it up now to a secure location: `maverick encryption backup-key --to "
        "<dir>` (or inject your own via MAVERICK_ENCRYPTION_KEY).",
        _KEY_PATH,
    )
    return key


def backup_key_material(dest_dir: Path) -> list[Path]:
    """Copy the at-rest key material to ``dest_dir`` for safe escrow.

    Copies the primary key (``at_rest.key``) and every rotation-keyring key
    (``at_rest.d/*.key``) into ``dest_dir``, each ``0600`` inside a ``0700``
    directory. Returns the paths written. Raises :class:`EncryptionUnavailable`
    when no key material exists yet (nothing has been sealed) or the copy fails.

    The copies are plaintext key material -- store them somewhere at least as
    protected as the originals (a secrets manager / offline vault), not next to
    the data they unlock. A key injected via ``MAVERICK_ENCRYPTION_KEY`` lives
    in your secrets manager already and is not on disk to copy.
    """
    sources: list[Path] = []
    if _KEY_PATH.exists():
        sources.append(_KEY_PATH)
    try:
        sources.extend(sorted(_keyring_dir().glob("*.key")))
    except OSError:
        pass
    if not sources:
        raise EncryptionUnavailable(
            f"no at-rest key material to back up under {_KEY_PATH.parent} "
            "(nothing has been sealed yet, or the key is injected via "
            "MAVERICK_ENCRYPTION_KEY and not stored on disk)."
        )
    try:
        dest_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(dest_dir, 0o700)
    except OSError as e:
        raise EncryptionUnavailable(
            f"cannot prepare key backup dir {dest_dir}: {e}"
        ) from e
    written: list[Path] = []
    for src in sources:
        dst = dest_dir / src.name
        try:
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o600)
        except OSError as e:
            raise EncryptionUnavailable(
                f"cannot copy key {src} -> {dst}: {e}"
            ) from e
        written.append(dst)
    return written


# --- rotation keyring -------------------------------------------------------
# Graceful key rotation: a directory of ``<keyid>.key`` files alongside the
# legacy single key. The NEWEST file is the active key (new v2 seals embed its
# 8-byte id); every prior key is retained so v2 blobs sealed under it still
# decrypt, and legacy v1 blobs keep decrypting under _load_or_create_key().
# Rotation is therefore additive -- no existing data is rewritten or lost.


def _key_fingerprint(key: bytes) -> bytes:
    return hashlib.sha256(key).digest()[:_KEYID_BYTES]


def _keyring_dir() -> Path:
    # Derived from _KEY_PATH.parent so tests that monkeypatch _KEY_PATH (or set
    # HOME) relocate the keyring with it.
    return _KEY_PATH.parent / "at_rest.d"


def _read_keyring_key(path: Path) -> bytes:
    try:
        st = path.stat()
        if st.st_mode & 0o077:
            os.chmod(path, 0o600)
        key = bytes.fromhex(path.read_text().strip())
    except (OSError, ValueError) as e:
        raise EncryptionUnavailable(f"cannot read at-rest key {path}: {e}") from e
    if len(key) != _KEY_BYTES:
        raise EncryptionUnavailable(f"at-rest key {path} is malformed")
    return key


def _active_keyring_key() -> tuple[bytes, bytes] | None:
    """``(key, keyid)`` of the newest keyring key, or None if the ring is empty
    (then sealing uses the legacy single-key v1 path, unchanged)."""
    try:
        keys = sorted(_keyring_dir().glob("*.key"))
    except OSError:
        return None
    if not keys:
        return None
    latest = max(keys, key=lambda p: p.stat().st_mtime)
    return _read_keyring_key(latest), bytes.fromhex(latest.stem)


def _resolve_key_by_id(keyid: bytes) -> bytes:
    """The key matching a v2 blob's ``keyid``: a keyring file, else the legacy
    key when its fingerprint matches (so a v1 deployment's key can also back v2)."""
    path = _keyring_dir() / (keyid.hex() + ".key")
    if path.exists():
        return _read_keyring_key(path)
    try:
        legacy = _load_or_create_key()
        if _key_fingerprint(legacy) == keyid:
            return legacy
    except EncryptionUnavailable:
        pass
    raise EncryptionUnavailable(
        f"no at-rest key for key-id {keyid.hex()}: the key that sealed this data "
        "is not available (a rotated key was removed, or the wrong keyring)."
    )


def rotate_at_rest_key() -> str:
    """Mint a new active at-rest key in the rotation keyring and return its id.

    Safe and additive: new seals immediately use the new key (v2 header), while
    all prior keys are retained so existing data stays readable -- no re-encrypt
    flag-day. Applies to the process-wide at-rest key (per-tenant envelope keys
    rotate via their own KMS). Takes effect for new seals right away.
    """
    if not _have_crypto():
        raise EncryptionUnavailable(
            "at-rest encryption needs the 'cryptography' package."
        )
    d = _keyring_dir()
    try:
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(d, 0o700)
    except OSError as e:
        raise EncryptionUnavailable(f"cannot secure keyring dir {d}: {e}") from e
    key = secrets.token_bytes(_KEY_BYTES)
    keyid = _key_fingerprint(key)
    path = d / (keyid.hex() + ".key")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key.hex())
        os.chmod(path, 0o600)
    except FileExistsError:  # astronomically unlikely id collision; caller retries
        raise EncryptionUnavailable("key-id collision; retry rotation") from None
    except OSError as e:
        raise EncryptionUnavailable(f"cannot write keyring key {path}: {e}") from e
    return keyid.hex()


def is_sealed(blob: bytes) -> bool:
    """True if ``blob`` was produced by :func:`seal` (carries a magic header).

    Recognises the v1 + v2 process-wide headers and the per-tenant envelope
    header, so strict-mode + TEXT-column detection treat sealed values as sealed."""
    return (
        blob[: len(_MAGIC)] == _MAGIC
        or blob[: len(_MAGIC_V2)] == _MAGIC_V2
        or blob[: len(_TENANT_MAGIC)] == _TENANT_MAGIC
    )


def seal(plaintext: bytes) -> bytes:
    """Encrypt with AES-256-GCM. Returns ``MAGIC || nonce || ciphertext+tag``.

    Raises :class:`EncryptionUnavailable` if crypto/key are missing (fail closed:
    the caller must not silently fall back to writing plaintext)."""
    # Per-tenant mode: route through the tenant's own data key. Output carries the
    # tenant magic header, so unseal()/is_sealed() handle it transparently and
    # globally-sealed data written before the switch still opens.
    if per_tenant_at_rest():
        from .paths import current_tenant
        from .tenant.kms import seal_for_tenant
        return seal_for_tenant(current_tenant(), plaintext)
    if not _have_crypto():
        raise EncryptionUnavailable(
            "at-rest encryption enabled but 'cryptography' is not installed "
            "(pip install 'maverick-agent[audit-signing]')"
        )
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = secrets.token_bytes(_NONCE_BYTES)
    # If the rotation keyring has been initialised (an operator ran
    # `maverick encryption rotate`), seal under the active key and embed its id
    # (v2). Otherwise keep the legacy single-key v1 path byte-for-byte unchanged.
    active = _active_keyring_key()
    if active is not None:
        key, keyid = active
        ct = AESGCM(key).encrypt(nonce, plaintext, None)
        return _MAGIC_V2 + keyid + nonce + ct
    key = _load_or_create_key()
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return _MAGIC + nonce + ct


def unseal(blob: bytes) -> bytes:
    """Decrypt a sealed blob. A blob *without* the magic header is returned
    unchanged — plaintext written before encryption was enabled (transparent
    migration). Raises :class:`EncryptionUnavailable` only when a genuinely
    sealed blob can't be opened."""
    # A per-tenant envelope is opened with the tenant's data key regardless of
    # whether per-tenant mode is currently on (so reads keep working after the
    # mode is toggled). The current tenant must match the one it was sealed under
    # — GCM authentication fails otherwise, which is the cross-tenant guarantee.
    if blob[: len(_TENANT_MAGIC)] == _TENANT_MAGIC:
        from .paths import current_tenant
        from .tenant.kms import unseal_for_tenant
        return unseal_for_tenant(current_tenant(), blob)
    if not is_sealed(blob):
        return blob
    if not _have_crypto():
        raise EncryptionUnavailable(
            "found encrypted data but 'cryptography' is not installed"
        )
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    # v2 (keyring): MAGIC_V2 || keyid(8) || nonce(12) || ct+tag. Resolve the key
    # by its embedded id so blobs sealed under a now-superseded key still open.
    if blob[: len(_MAGIC_V2)] == _MAGIC_V2:
        body = blob[len(_MAGIC_V2):]
        if len(body) < _KEYID_BYTES + _NONCE_BYTES + 16:
            raise EncryptionUnavailable(
                "sealed blob is truncated (too short for key-id + nonce + tag)"
            )
        keyid = body[:_KEYID_BYTES]
        nonce = body[_KEYID_BYTES:_KEYID_BYTES + _NONCE_BYTES]
        ct = body[_KEYID_BYTES + _NONCE_BYTES:]
        key = _resolve_key_by_id(keyid)
        try:
            return AESGCM(key).decrypt(nonce, ct, None)
        except InvalidTag as e:
            raise EncryptionUnavailable(
                "cannot decrypt sealed data: wrong at-rest key or altered "
                "ciphertext (GCM authentication failed)"
            ) from e

    key = _load_or_create_key()
    body = blob[len(_MAGIC):]
    # A sealed blob is MAGIC || 12-byte nonce || ciphertext+16-byte GCM tag.
    # Guard the length before slicing so a truncated blob raises the documented
    # EncryptionUnavailable, not a bare ValueError from AESGCM.
    if len(body) < _NONCE_BYTES + 16:
        raise EncryptionUnavailable(
            "sealed blob is truncated (too short to hold a nonce + GCM tag); "
            "the data is corrupt or not a Maverick at-rest blob"
        )
    nonce, ct = body[:_NONCE_BYTES], body[_NONCE_BYTES:]
    try:
        return AESGCM(key).decrypt(nonce, ct, None)
    except InvalidTag as e:
        # Wrong key (e.g. a rotated/restored key) or tampered ciphertext.
        # Honor the documented contract: surface EncryptionUnavailable rather
        # than leaking cryptography's InvalidTag, which callers that guard on
        # EncryptionUnavailable would not catch.
        raise EncryptionUnavailable(
            "cannot decrypt sealed data: wrong at-rest key or the ciphertext "
            "has been altered (GCM authentication failed)"
        ) from e


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
    """Return True only for structurally valid sealed TEXT-column tokens.

    The marker prefix is public, so callers must not treat a value as encrypted
    just because it starts with ``MVKAR1:``.  A legacy plaintext value may collide
    with that marker (or an attacker may forge the prefix).  Such values are not
    sealed and must remain visible to strict-mode guards and migration.
    """
    if not isinstance(s, str) or not s.startswith(_STR_PREFIX):
        return False
    try:
        blob = base64.b64decode(s[len(_STR_PREFIX):], validate=True)
    except (ValueError, binascii.Error):
        return False
    return is_sealed(blob) and len(blob) >= len(_MAGIC) + _NONCE_BYTES + 16


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
    "per_tenant_at_rest",
    "is_sealed",
    "is_sealed_str",
    "seal",
    "unseal",
    "seal_text",
    "unseal_to_text",
    "seal_to_str",
    "unseal_from_str",
    "rotate_at_rest_key",
    "backup_key_material",
    "EncryptionUnavailable",
]
