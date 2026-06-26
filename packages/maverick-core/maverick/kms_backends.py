"""Cloud KMS backends (BYOK) — the KEK lives in the customer's HSM/KMS.

The default :class:`maverick.tenant.kms.LocalKMS` derives the KEK in-process. A
regulated client that mandates **customer-managed keys** wants the KEK to never
leave their KMS/HSM; these backends implement the :class:`~maverick.tenant.kms.KMS`
``wrap``/``unwrap`` Protocol by delegating to the cloud KMS Encrypt/Decrypt API,
binding the tenant ``context`` as the KMS encryption context / AAD so a wrapped
DEK can't be unwrapped under the wrong tenant/purpose.

Selected by ``[kms] provider`` (``aws`` / ``gcp`` / ``vault``). SDKs are lazy
imports (optional extras); a missing SDK raises a clear install hint rather than
falling back to in-process keys. Clients are injectable for testing.

Config (``~/.maverick/config.toml``)::

    [kms]
    provider = "aws"                       # aws | gcp | vault | local
    key_id   = "arn:aws:kms:us-east-1:...:key/<uuid>"   # AWS key id/ARN,
                                           # GCP crypto-key resource name, or
                                           # Vault transit key name
    region   = "us-east-1"                 # AWS (or AWS_REGION)
    address  = "https://vault.internal:8200"   # Vault (or VAULT_ADDR)
    mount    = "transit"                   # Vault transit mount

Auth uses each SDK's standard chain (IAM role / ADC / VAULT_TOKEN).
"""
from __future__ import annotations

import base64
import os
from typing import Any

from .crypto_at_rest import EncryptionUnavailable

_AWS_MAGIC = b"MVKKMS-AWS1\n"
_GCP_MAGIC = b"MVKKMS-GCP1\n"
_VAULT_MAGIC = b"MVKKMS-VLT1\n"


def _kms_cfg() -> dict:
    try:
        from .config import load_config
        return (load_config() or {}).get("kms") or {}
    except Exception:  # pragma: no cover - config never blocks key setup
        return {}


def _require(value: str | None, what: str) -> str:
    if not value:
        raise EncryptionUnavailable(f"[kms] {what} is required for this provider")
    return value


def _ctx_b64(context: bytes | None) -> str:
    return base64.b64encode(context or b"").decode("ascii")


def _split_magic(magic: bytes, wrapped: bytes) -> bytes:
    if not wrapped.startswith(magic):
        raise EncryptionUnavailable("wrapped DEK is not from this KMS provider (bad magic)")
    return wrapped[len(magic):]


class AwsKmsKEK:
    """KEK in AWS KMS. ``wrap`` = ``kms:Encrypt`` with the tenant context as the
    EncryptionContext; ``unwrap`` = ``kms:Decrypt``."""

    def __init__(self, *, key_id: str | None = None, region: str | None = None,
                 client: Any | None = None, cfg: dict | None = None):
        cfg = cfg if cfg is not None else _kms_cfg()
        self.key_id = _require(key_id or os.environ.get("MAVERICK_KMS_KEY_ID")
                               or cfg.get("key_id"), "key_id")
        self.region = region or cfg.get("region") or os.environ.get("AWS_REGION")
        self._client = client

    def _kms(self):
        if self._client is None:
            try:
                import boto3  # type: ignore
            except ImportError as e:
                raise EncryptionUnavailable(
                    "AWS KMS backend needs boto3 (pip install boto3)") from e
            self._client = boto3.client("kms", region_name=self.region)
        return self._client

    def wrap(self, dek: bytes, *, context: bytes | None = None) -> bytes:
        resp = self._kms().encrypt(
            KeyId=self.key_id, Plaintext=dek,
            EncryptionContext={"maverick": _ctx_b64(context)})
        return _AWS_MAGIC + resp["CiphertextBlob"]

    def unwrap(self, wrapped: bytes, *, context: bytes | None = None) -> bytes:
        ct = _split_magic(_AWS_MAGIC, wrapped)
        resp = self._kms().decrypt(
            CiphertextBlob=ct,
            EncryptionContext={"maverick": _ctx_b64(context)})
        return resp["Plaintext"]


class GcpKmsKEK:
    """KEK in Google Cloud KMS. ``wrap``/``unwrap`` use Encrypt/Decrypt with the
    tenant context as ``additional_authenticated_data``."""

    def __init__(self, *, key_id: str | None = None, client: Any | None = None,
                 cfg: dict | None = None):
        cfg = cfg if cfg is not None else _kms_cfg()
        # GCP uses the full crypto-key resource name as the id.
        self.key_id = _require(key_id or os.environ.get("MAVERICK_KMS_KEY_ID")
                               or cfg.get("key_id"), "key_id")
        self._client = client

    def _kms(self):
        if self._client is None:
            try:
                from google.cloud import kms  # type: ignore
            except ImportError as e:
                raise EncryptionUnavailable(
                    "GCP KMS backend needs google-cloud-kms "
                    "(pip install google-cloud-kms)") from e
            self._client = kms.KeyManagementServiceClient()
        return self._client

    def wrap(self, dek: bytes, *, context: bytes | None = None) -> bytes:
        resp = self._kms().encrypt(request={
            "name": self.key_id, "plaintext": dek,
            "additional_authenticated_data": context or b""})
        return _GCP_MAGIC + resp.ciphertext

    def unwrap(self, wrapped: bytes, *, context: bytes | None = None) -> bytes:
        ct = _split_magic(_GCP_MAGIC, wrapped)
        resp = self._kms().decrypt(request={
            "name": self.key_id, "ciphertext": ct,
            "additional_authenticated_data": context or b""})
        return resp.plaintext


class VaultTransitKMS:
    """KEK in HashiCorp Vault's transit engine. The tenant context is passed as
    the transit ``context`` (the transit key must be created with
    ``derived=true`` so the context is bound into key derivation)."""

    def __init__(self, *, key_id: str | None = None, address: str | None = None,
                 token: str | None = None, mount: str | None = None,
                 client: Any | None = None, cfg: dict | None = None):
        cfg = cfg if cfg is not None else _kms_cfg()
        self.key_id = _require(key_id or os.environ.get("MAVERICK_KMS_KEY_ID")
                               or cfg.get("key_id"), "key_id")
        self.address = address or cfg.get("address") or os.environ.get("VAULT_ADDR")
        self.token = token or os.environ.get("VAULT_TOKEN")
        self.mount = mount or cfg.get("mount") or "transit"
        self._client = client

    def _vault(self):
        if self._client is None:
            try:
                import hvac  # type: ignore
            except ImportError as e:
                raise EncryptionUnavailable(
                    "Vault KMS backend needs hvac (pip install hvac)") from e
            self._client = hvac.Client(url=self.address, token=self.token)
        return self._client

    def wrap(self, dek: bytes, *, context: bytes | None = None) -> bytes:
        resp = self._vault().secrets.transit.encrypt_data(
            name=self.key_id, mount_point=self.mount,
            plaintext=base64.b64encode(dek).decode("ascii"),
            context=_ctx_b64(context))
        ciphertext = resp["data"]["ciphertext"]  # "vault:v1:..."
        return _VAULT_MAGIC + ciphertext.encode("utf-8")

    def unwrap(self, wrapped: bytes, *, context: bytes | None = None) -> bytes:
        ciphertext = _split_magic(_VAULT_MAGIC, wrapped).decode("utf-8")
        resp = self._vault().secrets.transit.decrypt_data(
            name=self.key_id, mount_point=self.mount,
            ciphertext=ciphertext, context=_ctx_b64(context))
        return base64.b64decode(resp["data"]["plaintext"])


_PROVIDERS = {"aws": AwsKmsKEK, "gcp": GcpKmsKEK, "vault": VaultTransitKMS}


def build_cloud_kms(provider: str, cfg: dict | None = None):
    """Construct the cloud KMS backend for ``provider`` (aws/gcp/vault).

    ``cfg`` is an explicit ``[kms]`` section (key_id/region/address/mount). Pass
    a tenant's resolved config for deterministic per-tenant BYOK — without it the
    backend reads the ambient ``load_config()`` (which depends on the active
    tenant context). Raises :class:`EncryptionUnavailable` for an unknown
    provider (fail-closed — never silently fall back to in-process keys).
    Construction is cheap; the SDK client is built lazily on first wrap/unwrap.
    """
    cls = _PROVIDERS.get((provider or "").strip().lower())
    if cls is None:
        raise EncryptionUnavailable(
            f"[kms] provider={provider!r} is not a known backend "
            f"(expected one of: local, {', '.join(sorted(_PROVIDERS))})")
    return cls(cfg=cfg)


__all__ = ["AwsKmsKEK", "GcpKmsKEK", "VaultTransitKMS", "build_cloud_kms"]
