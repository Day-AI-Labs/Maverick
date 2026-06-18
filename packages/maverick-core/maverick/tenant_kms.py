"""Per-tenant envelope encryption — a DEK per tenant, wrapped by a KMS KEK.

:mod:`maverick.crypto_at_rest` seals data with **one** process-wide key — correct
for a single-tenant box, wrong for a hosted multi-tenant store where one process
must not hold a master key that opens every tenant's data. This module adds the
standard envelope pattern:

  - each tenant has its own **Data Encryption Key** (DEK), used to AES-256-GCM
    its data at rest;
  - each DEK is stored only in **wrapped** form (encrypted by a **Key Encryption
    Key**, the KEK), under the tenant's own ``keys/dek.wrapped`` (chmod 600);
  - the KEK lives in a :class:`KMS`. The default :class:`LocalKMS` derives the
    KEK from the at-rest key material (or ``MAVERICK_KMS_KEK``); a cloud KMS
    (AWS/GCP/Vault) is a drop-in that implements ``wrap``/``unwrap`` so the KEK
    never leaves the HSM.

Rotating the KEK (re-wrap the same DEK) is instant and re-encrypts nothing;
rotating a DEK requires re-encrypting that tenant's data and is a separate op.
Opt-in and offline-testable. Requires the ``cryptography`` extra (AES-GCM).
"""
from __future__ import annotations

import hashlib
import os
import secrets
import threading
from typing import Protocol

from .crypto_at_rest import EncryptionUnavailable, _have_crypto
from .paths import data_dir

_DEK_BYTES = 32
_NONCE_BYTES = 12
_GCM_TAG_BYTES = 16
_WRAP_MAGIC = b"MVKDEK1\n"   # a wrapped DEK
_SEAL_MAGIC = b"MVKTEN1\n"   # a tenant-sealed blob


class KMS(Protocol):
    """Key Encryption Key operations. ``wrap``/``unwrap`` a 32-byte DEK.

    ``context`` is authenticated metadata (for example tenant id and purpose)
    that must match on unwrap, preventing wrapped DEKs from being transplanted
    between tenants or uses.
    """

    def wrap(self, dek: bytes, *, context: bytes | None = None) -> bytes: ...
    def unwrap(self, wrapped: bytes, *, context: bytes | None = None) -> bytes: ...


def _aesgcm(key: bytes):
    if not _have_crypto():
        raise EncryptionUnavailable(
            "per-tenant KMS needs the 'cryptography' extra "
            "(pip install 'maverick-agent[audit-signing]')")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key)


def _gcm_seal(
    key: bytes,
    magic: bytes,
    plaintext: bytes,
    associated_data: bytes | None = None,
) -> bytes:
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ct = _aesgcm(key).encrypt(nonce, plaintext, associated_data)
    return magic + nonce + ct


def _gcm_open(
    key: bytes,
    magic: bytes,
    blob: bytes,
    associated_data: bytes | None = None,
) -> bytes:
    from cryptography.exceptions import InvalidTag

    if blob[: len(magic)] != magic:
        raise EncryptionUnavailable("blob is not a Maverick KMS envelope (bad magic)")
    body = blob[len(magic):]
    if len(body) < _NONCE_BYTES + _GCM_TAG_BYTES:
        raise EncryptionUnavailable("KMS envelope is truncated")
    nonce, ct = body[:_NONCE_BYTES], body[_NONCE_BYTES:]
    try:
        return _aesgcm(key).decrypt(nonce, ct, associated_data)
    except InvalidTag as e:
        raise EncryptionUnavailable(
            "cannot open KMS envelope: wrong key or altered ciphertext") from e


def _tenant_context(tenant_id: str | None, purpose: bytes) -> bytes:
    """Canonical AEAD/KMS context for tenant-bound envelopes."""
    tenant = (tenant_id or "__default__").encode("utf-8")
    return (
        b"maverick-tenant-kms/v1\x00"
        + purpose
        + b"\x00"
        + str(len(tenant)).encode("ascii")
        + b":"
        + tenant
    )


def _resolve_local_kek() -> bytes:
    """The local KEK: ``MAVERICK_KMS_KEK`` (hex/base64, 32 bytes) if set, else a
    stable derivation from the at-rest master key — so no new key file to manage
    and rotating the at-rest key rotates the KEK."""
    raw = os.environ.get("MAVERICK_KMS_KEK")
    if raw:
        from .crypto_at_rest import _decode_injected_key
        kek = _decode_injected_key(raw)
        if len(kek) != _DEK_BYTES:
            raise EncryptionUnavailable(
                f"MAVERICK_KMS_KEK must decode to {_DEK_BYTES} bytes, got {len(kek)}")
        return kek
    from .crypto_at_rest import _load_or_create_key
    master = _load_or_create_key()
    # Domain-separated derivation so the KEK is distinct from the at-rest data key.
    return hashlib.sha256(b"maverick-kms-kek/v1\x00" + master).digest()


class LocalKMS:
    """KEK held in-process (derived from the at-rest key, or ``MAVERICK_KMS_KEK``).
    Wraps DEKs with AES-256-GCM. The default provider for self-hosted deploys."""

    def __init__(self, kek: bytes | None = None):
        self._kek = kek if kek is not None else _resolve_local_kek()
        if len(self._kek) != _DEK_BYTES:
            raise EncryptionUnavailable("KEK must be 32 bytes")

    def wrap(self, dek: bytes, *, context: bytes | None = None) -> bytes:
        return _gcm_seal(self._kek, _WRAP_MAGIC, dek, context)

    def unwrap(self, wrapped: bytes, *, context: bytes | None = None) -> bytes:
        return _gcm_open(self._kek, _WRAP_MAGIC, wrapped, context)


def get_kms() -> KMS:
    """The active KMS provider. ``[kms] provider`` selects it; default local."""
    try:
        from .config import load_config
        provider = str((load_config() or {}).get("kms", {}).get("provider") or "local")
    except Exception:
        provider = "local"
    if provider not in ("", "local"):
        # Cloud KMS (aws/gcp/vault): the KEK stays in the customer's HSM (BYOK).
        # An unknown provider, or a missing SDK, raises EncryptionUnavailable
        # rather than silently falling back to in-process LocalKMS -- a configured
        # HSM-backed provider must never be downgraded to in-process key material
        # (fail-closed, consistent with crypto_at_rest). Callers surface this
        # (doctor's at-rest check, the audit-seal CLI) rather than writing plaintext.
        from .kms_backends import build_cloud_kms
        return build_cloud_kms(provider)
    return LocalKMS()


def _wrapped_dek_path(tenant_id: str | None):
    return data_dir("keys", "dek.wrapped", tenant=tenant_id)


_dek_cache: dict[str, bytes] = {}
_dek_lock = threading.Lock()


def tenant_dek(tenant_id: str | None, *, kms: KMS | None = None) -> bytes:
    """The tenant's Data Encryption Key (unwrapped). Loads the wrapped DEK, or
    generates + wraps + persists one on first use. Cached per tenant id."""
    cache_key = tenant_id or "__default__"
    with _dek_lock:
        cached = _dek_cache.get(cache_key)
        if cached is not None:
            return cached
        kms = kms or get_kms()
        path = _wrapped_dek_path(tenant_id)
        context = _tenant_context(tenant_id, b"dek-wrap")
        if path.exists():
            dek = kms.unwrap(path.read_bytes(), context=context)
            if len(dek) != _DEK_BYTES:
                raise EncryptionUnavailable("unwrapped DEK is malformed")
        else:
            dek = secrets.token_bytes(_DEK_BYTES)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            wrapped = kms.wrap(dek, context=context)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(wrapped)
        _dek_cache[cache_key] = dek
        return dek


def seal_for_tenant(tenant_id: str | None, plaintext: bytes, *, kms: KMS | None = None) -> bytes:
    """AES-256-GCM ``plaintext`` under the tenant's DEK."""
    context = _tenant_context(tenant_id, b"tenant-data")
    return _gcm_seal(tenant_dek(tenant_id, kms=kms), _SEAL_MAGIC, plaintext, context)


def unseal_for_tenant(tenant_id: str | None, blob: bytes, *, kms: KMS | None = None) -> bytes:
    """Inverse of :func:`seal_for_tenant`."""
    context = _tenant_context(tenant_id, b"tenant-data")
    return _gcm_open(tenant_dek(tenant_id, kms=kms), _SEAL_MAGIC, blob, context)


def seal_text_for_tenant(tenant_id: str | None, text: str, **kw) -> bytes:
    return seal_for_tenant(tenant_id, text.encode("utf-8"), **kw)


def unseal_text_for_tenant(tenant_id: str | None, blob: bytes, **kw) -> str:
    return unseal_for_tenant(tenant_id, blob, **kw).decode("utf-8", errors="replace")


def rotate_kek(tenant_id: str | None, *, old_kms: KMS, new_kms: KMS) -> None:
    """Re-wrap the tenant's existing DEK under a new KEK (instant; re-encrypts no
    data). The data-key is unchanged, so already-sealed data stays readable."""
    path = _wrapped_dek_path(tenant_id)
    if not path.exists():
        raise EncryptionUnavailable(f"no wrapped DEK for tenant {tenant_id!r} to rotate")
    context = _tenant_context(tenant_id, b"dek-wrap")
    dek = old_kms.unwrap(path.read_bytes(), context=context)
    if len(dek) != _DEK_BYTES:
        raise EncryptionUnavailable("unwrapped DEK is malformed")
    rewrapped = new_kms.wrap(dek, context=context)
    tmp = path.with_suffix(".wrapped.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(rewrapped)
    os.replace(tmp, path)
    with _dek_lock:
        _dek_cache.pop(tenant_id or "__default__", None)


def _clear_cache() -> None:
    """Drop the in-memory DEK cache (tests / after a rotation)."""
    with _dek_lock:
        _dek_cache.clear()


__all__ = [
    "KMS", "LocalKMS", "get_kms",
    "tenant_dek", "seal_for_tenant", "unseal_for_tenant",
    "seal_text_for_tenant", "unseal_text_for_tenant", "rotate_kek",
]
