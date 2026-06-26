"""BYOK cloud KMS backends (AWS / GCP / Vault) behind the tenant_kms.KMS
Protocol. Fakes use real AES-GCM so context binding is actually exercised."""
from __future__ import annotations

import base64
import json
import os
import types

import pytest

pytest.importorskip("cryptography")
from cryptography.exceptions import InvalidTag  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
from maverick import kms_backends  # noqa: E402
from maverick.crypto_at_rest import EncryptionUnavailable  # noqa: E402
from maverick.tenant import kms as tenant_kms  # noqa: E402

_FIXED_KEK = b"\x11" * 32


def _enc(plaintext: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_FIXED_KEK).encrypt(nonce, plaintext, aad)


def _dec(blob: bytes, aad: bytes) -> bytes:
    return AESGCM(_FIXED_KEK).decrypt(blob[:12], blob[12:], aad)


# ---- fake SDK clients (match each SDK's response shape) --------------------


class _FakeAws:
    def encrypt(self, KeyId, Plaintext, EncryptionContext):  # noqa: N803
        aad = json.dumps(EncryptionContext, sort_keys=True).encode()
        return {"CiphertextBlob": _enc(Plaintext, aad)}

    def decrypt(self, CiphertextBlob, EncryptionContext):  # noqa: N803
        aad = json.dumps(EncryptionContext, sort_keys=True).encode()
        return {"Plaintext": _dec(CiphertextBlob, aad)}


class _FakeGcp:
    def encrypt(self, request):
        aad = request["additional_authenticated_data"]
        ct = _enc(request["plaintext"], aad)
        return types.SimpleNamespace(ciphertext=ct)

    def decrypt(self, request):
        aad = request["additional_authenticated_data"]
        pt = _dec(request["ciphertext"], aad)
        return types.SimpleNamespace(plaintext=pt)


class _FakeVault:
    class _Transit:
        def encrypt_data(self, name, mount_point, plaintext, context):
            aad = context.encode()
            ct = _enc(base64.b64decode(plaintext), aad)
            return {"data": {"ciphertext": "vault:v1:" + base64.b64encode(ct).decode()}}

        def decrypt_data(self, name, mount_point, ciphertext, context):
            aad = context.encode()
            ct = base64.b64decode(ciphertext.split("vault:v1:", 1)[1])
            return {"data": {"plaintext": base64.b64encode(_dec(ct, aad)).decode()}}

    def __init__(self):
        self.secrets = types.SimpleNamespace(transit=self._Transit())


_BACKENDS = [
    lambda: kms_backends.AwsKmsKEK(key_id="k", client=_FakeAws()),
    lambda: kms_backends.GcpKmsKEK(key_id="k", client=_FakeGcp()),
    lambda: kms_backends.VaultTransitKMS(key_id="k", client=_FakeVault()),
]


@pytest.mark.parametrize("make", _BACKENDS)
def test_wrap_unwrap_round_trip(make):
    kms = make()
    dek = b"\x42" * 32
    ctx = b"tenant:acme"
    wrapped = kms.wrap(dek, context=ctx)
    assert wrapped != dek
    assert kms.unwrap(wrapped, context=ctx) == dek


@pytest.mark.parametrize("make", _BACKENDS)
def test_context_binding_enforced(make):
    kms = make()
    wrapped = kms.wrap(b"\x42" * 32, context=b"tenant:acme")
    with pytest.raises(InvalidTag):  # wrong context -> AEAD auth failure
        kms.unwrap(wrapped, context=b"tenant:evil")


@pytest.mark.parametrize("make", _BACKENDS)
def test_wrong_provider_magic_rejected(make):
    kms = make()
    with pytest.raises(EncryptionUnavailable):
        kms.unwrap(b"NOT-OUR-MAGIC" + b"x" * 40, context=b"c")


# ---- factory + get_kms dispatch -------------------------------------------


def test_build_cloud_kms_dispatch(monkeypatch):
    monkeypatch.setattr("maverick.config.load_config",
                        lambda: {"kms": {"provider": "aws", "key_id": "k"}})
    assert isinstance(kms_backends.build_cloud_kms("aws"), kms_backends.AwsKmsKEK)
    assert isinstance(kms_backends.build_cloud_kms("gcp"), kms_backends.GcpKmsKEK)
    assert isinstance(kms_backends.build_cloud_kms("vault"),
                      kms_backends.VaultTransitKMS)


def test_build_cloud_kms_unknown_fails():
    with pytest.raises(EncryptionUnavailable):
        kms_backends.build_cloud_kms("oracle")


def test_missing_key_id_fails(monkeypatch):
    monkeypatch.setattr("maverick.config.load_config", lambda: {"kms": {}})
    monkeypatch.delenv("MAVERICK_KMS_KEY_ID", raising=False)
    with pytest.raises(EncryptionUnavailable):
        kms_backends.AwsKmsKEK()


def test_get_kms_routes_to_cloud(monkeypatch):
    monkeypatch.setattr("maverick.config.load_config",
                        lambda: {"kms": {"provider": "vault", "key_id": "k"}})
    assert isinstance(tenant_kms.get_kms(), kms_backends.VaultTransitKMS)


def test_get_kms_local_default(monkeypatch):
    monkeypatch.setattr("maverick.config.load_config", lambda: {"kms": {"provider": "local"}})
    assert isinstance(tenant_kms.get_kms(), tenant_kms.LocalKMS)


def test_get_kms_unknown_provider_fails(monkeypatch):
    monkeypatch.setattr("maverick.config.load_config", lambda: {"kms": {"provider": "oracle"}})
    with pytest.raises(EncryptionUnavailable):
        tenant_kms.get_kms()


# ---- integration: tenant seal/unseal through a cloud KEK ------------------


def test_tenant_seal_through_cloud_kms(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_CLIENT_ID", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    tenant_kms._clear_cache()
    kms = kms_backends.AwsKmsKEK(key_id="k", client=_FakeAws())
    blob = tenant_kms.seal_for_tenant("acme", b"phi-data", kms=kms)
    assert b"phi-data" not in blob
    assert tenant_kms.unseal_for_tenant("acme", blob, kms=kms) == b"phi-data"
    tenant_kms._clear_cache()
