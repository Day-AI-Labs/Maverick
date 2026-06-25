"""Fleet-scale per-tenant KMS (#20): per-tenant BYOK provider selection, a
DEK-cache TTL so a revoked key takes effect, and fleet-wide KEK rotation."""
from __future__ import annotations

import pytest

importorskip = pytest.importorskip
importorskip("cryptography")

from maverick.tenant import kms as K  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / ".maverick"))
    monkeypatch.setenv("MAVERICK_KMS_KEK", "ab" * 32)  # deterministic local KEK
    monkeypatch.delenv("MAVERICK_KMS_DEK_CACHE_TTL", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    K._clear_cache()
    yield
    K._clear_cache()


def _write_tenant_kms(tid: str, body: str) -> None:
    from maverick.paths import _tenant_segment, maverick_home
    d = maverick_home() / "tenants" / _tenant_segment(tid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.toml").write_text(body, encoding="utf-8")


# ---- per-tenant BYOK ------------------------------------------------------

def test_no_overlay_uses_local_kms():
    assert isinstance(K.get_kms("plain-tenant"), K.LocalKMS)
    assert isinstance(K.get_kms(None), K.LocalKMS)


def test_each_tenant_resolves_its_own_provider_and_key(monkeypatch):
    # Tenant A pins AWS KMS with its own key; tenant B stays local. Resolution is
    # deterministic — independent of the active tenant context.
    _write_tenant_kms("acme", '[kms]\nprovider = "aws"\nkey_id = "acme-cmk"\nregion = "us-east-1"\n')
    _write_tenant_kms("globex", '[kms]\nprovider = "local"\n')

    acme = K.get_kms("acme")
    from maverick.kms_backends import AwsKmsKEK
    assert isinstance(acme, AwsKmsKEK)
    assert acme.key_id == "acme-cmk"        # the TENANT's key, not ambient
    assert acme.region == "us-east-1"
    assert isinstance(K.get_kms("globex"), K.LocalKMS)


def test_byok_resolution_ignores_ambient_context(monkeypatch):
    # Even with a different tenant active in the context, get_kms(tid) reads tid's
    # config — so a fleet op rotating tenant X never wraps with tenant Y's key.
    _write_tenant_kms("xcorp", '[kms]\nprovider = "aws"\nkey_id = "xcorp-cmk"\n')
    monkeypatch.setenv("MAVERICK_TENANT", "someone-else")
    from maverick.kms_backends import AwsKmsKEK
    k = K.get_kms("xcorp")
    assert isinstance(k, AwsKmsKEK) and k.key_id == "xcorp-cmk"


# ---- DEK cache TTL --------------------------------------------------------

class _CountingKMS:
    """LocalKMS that counts unwrap calls, to observe cache re-validation."""
    def __init__(self):
        self._inner = K.LocalKMS()
        self.unwraps = 0

    def wrap(self, dek, *, context=None):
        return self._inner.wrap(dek, context=context)

    def unwrap(self, wrapped, *, context=None):
        self.unwraps += 1
        return self._inner.unwrap(wrapped, context=context)


def test_default_ttl_caches_for_process_lifetime():
    kms = _CountingKMS()
    K.tenant_dek("t", kms=kms)          # generate + wrap (no unwrap)
    K.tenant_dek("t", kms=kms)          # cache hit
    assert kms.unwraps == 0             # default TTL 0 -> never re-unwraps


def test_positive_ttl_re_unwraps_after_expiry(monkeypatch):
    monkeypatch.setenv("MAVERICK_KMS_DEK_CACHE_TTL", "100")
    clock = {"t": 1000.0}
    monkeypatch.setattr(K, "_now", lambda: clock["t"])
    kms = _CountingKMS()

    K.tenant_dek("t", kms=kms)          # gen + cache with expiry=1100
    K.tenant_dek("t", kms=kms)          # within TTL -> cache hit
    assert kms.unwraps == 0
    clock["t"] = 1200.0                 # past expiry
    K.tenant_dek("t", kms=kms)          # lapsed -> re-reads wrapped file + unwrap
    assert kms.unwraps == 1


# ---- fleet KEK rotation ---------------------------------------------------

def test_rotate_kek_fleet_rotates_all_provisioned_tenants(monkeypatch):
    from maverick.tenant import registry
    registry.create_tenant("a")
    registry.create_tenant("b")
    registry.create_tenant("c")  # provisioned but never seals -> no DEK

    old = K.LocalKMS(bytes.fromhex("ab" * 32))
    new = K.LocalKMS(bytes.fromhex("cd" * 32))
    # Seal data for a and b under the OLD kek so there's a DEK to rotate.
    for tid in ("a", "b"):
        K.seal_for_tenant(tid, b"secret-" + tid.encode(), kms=old)
    K._clear_cache()

    report = K.rotate_kek_fleet(old_kms_for=lambda t: old, new_kms_for=lambda t: new)
    assert report == {"a": "rotated", "b": "rotated"}   # c skipped (no DEK)

    # Data still readable, now under the NEW kek; the old kek can't unwrap.
    K._clear_cache()
    assert K.unseal_for_tenant("a", K.seal_for_tenant("a", b"x", kms=new), kms=new)
    K._clear_cache()
    from maverick.crypto_at_rest import EncryptionUnavailable
    with pytest.raises(EncryptionUnavailable):
        K.tenant_dek("a", kms=old)


def test_rotate_kek_fleet_isolates_per_tenant_failure(monkeypatch):
    from maverick.tenant import registry
    registry.create_tenant("good")
    registry.create_tenant("bad")
    old = K.LocalKMS(bytes.fromhex("ab" * 32))
    new = K.LocalKMS(bytes.fromhex("cd" * 32))
    for tid in ("good", "bad"):
        K.seal_for_tenant(tid, b"d", kms=old)
    K._clear_cache()

    def new_for(t):
        if t == "bad":
            raise RuntimeError("kms unreachable")
        return new

    report = K.rotate_kek_fleet(old_kms_for=lambda t: old, new_kms_for=new_for)
    assert report["good"] == "rotated"
    assert report["bad"].startswith("error:")
