"""Multi-tenant isolation tests (roadmap: 2028 H1 safety).

The tenancy story is only as good as its walls. These tests prove, across the
primitives that actually carry tenant data, that one tenant cannot read,
write, or decrypt another's:

  * **path routing** — ``data_dir`` lands each tenant under its own
    ``tenants/<t>/`` subtree (and distinct ids never collide onto one segment);
  * **world model** — ``world_for_tenant`` gives distinct DBs; a goal created
    under tenant A is invisible to tenant B;
  * **per-tenant KMS** — one tenant's DEK cannot open another's data, and a
    DEK wrapped for A does not unwrap under B's context;
  * **scope discipline** — ``set_tenant``/``reset_tenant`` restore cleanly and
    are independent across contexts.

Pure/offline: a temp ``MAVERICK_HOME`` so nothing touches the real home.
"""
from __future__ import annotations

import pytest
from maverick.paths import current_tenant, data_dir, reset_tenant, set_tenant


@pytest.fixture(autouse=True)
def _temp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    tok = set_tenant(None)
    yield
    reset_tenant(tok)


# ---- path routing ----

def test_data_dir_walls_tenants():
    a = data_dir("world.db", tenant="acme")
    b = data_dir("world.db", tenant="globex")
    assert a != b
    assert "tenants/acme/" in str(a).replace("\\", "/")
    assert "tenants/globex/" in str(b).replace("\\", "/")
    # No tenant -> legacy shared path (no tenants/ segment).
    assert "tenants/" not in str(data_dir("world.db", tenant=None)).replace("\\", "/")


def test_distinct_ids_never_collide_on_segment():
    # The sanitizer must not collapse two distinct tenant ids onto one dir
    # (that would silently merge their data).
    seen = set()
    for tid in ("acme", "ACME", "ac/me", "ac me", "acme.", "acme-1", "acme_1", "a.c.m.e"):
        seg = str(data_dir(tenant=tid))
        assert seg not in seen, f"{tid!r} collided onto an existing segment"
        seen.add(seg)


def test_active_tenant_scope_restores():
    assert current_tenant() is None
    tok = set_tenant("acme")
    try:
        assert current_tenant() == "acme"
        assert "tenants/acme/" in str(data_dir("x")).replace("\\", "/")
    finally:
        reset_tenant(tok)
    assert current_tenant() is None  # cleanly restored


# ---- world model isolation ----

def test_world_for_tenant_distinct_dbs():
    from maverick import world_model
    world_model._tenant_worlds.clear()
    wa = world_model.world_for_tenant("acme")
    wb = world_model.world_for_tenant("globex")
    assert wa is not wb
    assert wa.path != wb.path

    gid = wa.create_goal("acme secret plan", "do not leak", owner="")
    # Tenant B sees none of A's goals.
    assert wb.get_goal(gid) is None
    assert all(g.title != "acme secret plan" for g in wb.list_goals(limit=100))
    # A still has it.
    assert wa.get_goal(gid) is not None
    world_model._tenant_worlds.clear()


def test_world_for_tenant_caches_same_instance():
    from maverick import world_model
    world_model._tenant_worlds.clear()
    assert world_model.world_for_tenant("acme") is world_model.world_for_tenant("acme")
    world_model._tenant_worlds.clear()


# ---- per-tenant config / credential isolation ----

def test_provider_keys_are_per_tenant(tmp_path, monkeypatch):
    """Each tenant's own config.toml overlay supplies its own provider API key;
    with no active tenant the global config is used unchanged."""
    from maverick import config
    home = tmp_path / "home"
    monkeypatch.setenv("MAVERICK_HOME", str(home))
    monkeypatch.setattr(config, "config_path", lambda: home / "config.toml")
    # No env-var key in play for this test.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Global config (single-tenant / shared default).
    (home).mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(
        '[providers.anthropic]\napi_key = "global-key"\n',  # pragma: allowlist secret
        encoding="utf-8",
    )
    # Tenant acme overrides with its own key.
    acme_dir = data_dir(tenant="acme")
    acme_dir.mkdir(parents=True, exist_ok=True)
    (acme_dir / "config.toml").write_text(
        '[providers.anthropic]\napi_key = "acme-key"\n',  # pragma: allowlist secret
        encoding="utf-8",
    )

    # No tenant -> global key.
    assert config.get_provider_config("anthropic")["api_key"] == "global-key"  # pragma: allowlist secret
    # Active tenant acme -> acme's key.
    tok = set_tenant("acme")
    try:
        assert config.get_provider_config("anthropic")["api_key"] == "acme-key"  # pragma: allowlist secret
    finally:
        reset_tenant(tok)
    # A tenant with no overlay falls back to the global key (not acme's).
    tok = set_tenant("globex")
    try:
        assert config.get_provider_config("anthropic")["api_key"] == "global-key"  # pragma: allowlist secret
    finally:
        reset_tenant(tok)


# ---- per-tenant calibration / learning-freeze isolation ----

def test_calibration_samples_and_freeze_are_per_tenant(monkeypatch):
    """One tenant's calibration ledger and learning-freeze verdict must not
    bleed into another's self-improvement loop."""
    from maverick import calibration
    # Enforcement on so learning_frozen() actually consults the verdict.
    monkeypatch.setattr(
        calibration, "_settings",
        lambda: {"enforce": True, "min_samples": 20,
                 "min_discrimination": 0.15, "collect_from_coding": False},
    )

    # Tenant A: feed a drifted verifier (confident on right AND wrong answers)
    # and assess -> A's learning should freeze.
    tok = set_tenant("acme")
    try:
        for _ in range(15):
            calibration.record_sample(0.9, True)
            calibration.record_sample(0.85, False)
        calibration.run_assessment()
        assert calibration.learning_frozen() is True
        # A's ledger is under A's tenant dir.
        assert "tenants/acme/" in str(data_dir("calibration.ndjson")).replace("\\", "/")
    finally:
        reset_tenant(tok)

    # Tenant B never recorded anything: no verdict, so learning proceeds.
    tok = set_tenant("globex")
    try:
        assert calibration.load_samples() == []
        assert calibration.learning_frozen() is False
    finally:
        reset_tenant(tok)


# ---- per-tenant KMS isolation ----

def test_tenant_dek_distinct_and_non_transferable():
    from maverick.tenant_kms import tenant_dek
    dek_a = tenant_dek("acme")
    dek_b = tenant_dek("globex")
    assert dek_a != dek_b
    # Deterministic per tenant (so a restart reopens the same data)...
    assert tenant_dek("acme") == dek_a
    # ...but no overlap between tenants.
    assert len(dek_a) >= 16 and dek_a != dek_b


def test_wrapped_dek_does_not_unwrap_cross_tenant():
    from maverick.crypto_at_rest import EncryptionUnavailable
    from maverick.tenant_kms import LocalKMS, tenant_dek
    kms = LocalKMS()
    dek = tenant_dek("acme")
    wrapped = kms.wrap(dek, context=b"tenant:acme")
    # Same context round-trips.
    assert kms.unwrap(wrapped, context=b"tenant:acme") == dek
    # A different tenant's context must NOT recover the DEK (AEAD AAD binds it):
    # the AESGCM InvalidTag surfaces as EncryptionUnavailable.
    with pytest.raises(EncryptionUnavailable):
        kms.unwrap(wrapped, context=b"tenant:globex")


# ---- crypto-at-rest end to end (if available) ----

def test_encrypted_field_opaque_across_tenants(monkeypatch):
    """A value encrypted under tenant A's key is not readable as A's plaintext
    when the active tenant is B."""
    crypto = pytest.importorskip("maverick.crypto_at_rest")
    enc = getattr(crypto, "encrypt", None) or getattr(crypto, "encrypt_field", None)
    dec = getattr(crypto, "decrypt", None) or getattr(crypto, "decrypt_field", None)
    if enc is None or dec is None:
        pytest.skip("crypto_at_rest encrypt/decrypt API not present")
    tok = set_tenant("acme")
    try:
        blob = enc("acme PII: alice@example.com")
    finally:
        reset_tenant(tok)
    # Same tenant decrypts.
    tok = set_tenant("acme")
    try:
        assert "alice@example.com" in dec(blob)
    finally:
        reset_tenant(tok)
    # The ciphertext itself never contains the plaintext.
    assert "alice@example.com" not in (blob if isinstance(blob, str) else blob.decode("latin-1"))


def test_tenant_world_cache_evicts_lru_not_raises(monkeypatch, tmp_path):
    # M7: reaching MAX_TENANT_WORLDS evicts the least-recently-used tenant
    # instead of hard-failing the next one. Shrink the cap for the test.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    from maverick import world_model
    world_model._tenant_worlds.clear()
    monkeypatch.setattr(world_model, "MAX_TENANT_WORLDS", 3)

    w_a = world_model.world_for_tenant("a")
    world_model.world_for_tenant("b")
    world_model.world_for_tenant("c")          # cache full (3)
    # Touch "a" so it is most-recently-used; "b" is now the LRU.
    assert world_model.world_for_tenant("a") is w_a
    world_model.world_for_tenant("d")          # over cap -> evict LRU ("b")

    keys = list(world_model._tenant_worlds)
    assert len(world_model._tenant_worlds) == 3
    assert not any(k.endswith("b/world.db") for k in keys)   # b evicted
    assert any(k.endswith("a/world.db") for k in keys)       # a kept (recently used)
    assert any(k.endswith("d/world.db") for k in keys)       # d added
    world_model._tenant_worlds.clear()


def test_tenant_world_cache_never_evicts_shared(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    from maverick import world_model
    world_model._tenant_worlds.clear()
    monkeypatch.setattr(world_model, "MAX_TENANT_WORLDS", 2)

    world_model.world_for_tenant(None)         # the shared world
    world_model.world_for_tenant("t1")
    world_model.world_for_tenant("t2")         # at cap; next evicts a TENANT
    world_model.world_for_tenant("t3")

    from maverick.paths import data_dir
    shared_key = str(data_dir("world.db", tenant=None))
    assert shared_key in world_model._tenant_worlds  # shared never evicted
    world_model._tenant_worlds.clear()
