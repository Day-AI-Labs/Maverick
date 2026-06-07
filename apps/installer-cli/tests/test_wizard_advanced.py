"""The wizard's 'Advanced reasoning' step writes the kernel's opt-in config
sections, and the keys it writes are exactly the ones the kernel modules
read (the rule-6 integrity check: a wizard toggle must actually reach the
feature)."""
from __future__ import annotations

try:
    import tomllib  # 3.11+
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


def _write(cfg_dir, monkeypatch, advanced, capabilities=None):
    monkeypatch.setattr("maverick_installer.wizard.CONFIG_DIR", cfg_dir)
    monkeypatch.setattr("maverick_installer.wizard.ENV_FILE", cfg_dir / ".env")
    monkeypatch.setattr("maverick_installer.wizard.CONFIG_FILE", cfg_dir / "config.toml")
    from maverick_installer.wizard import write_config
    write_config(
        providers=["anthropic"], role_models={},
        channels={}, safety={"profile": "balanced"},
        budget={"max_dollars": 5.0, "max_wall_seconds": 600, "max_tool_calls": 30},
        sandbox={"backend": "local", "workdir": "~/ws"},
        keys={"ANTHROPIC_API_KEY": "x"},
        capabilities=capabilities or {}, advanced=advanced,
    )
    return (cfg_dir / "config.toml").read_text()


def test_advanced_all_on_writes_kernel_sections(tmp_path, monkeypatch):
    cfg = _write(tmp_path, monkeypatch, {
        "cost_aware": True, "verify_ensemble": True,
        "tree_of_thought": True, "compact_history": True, "reflexion": True,
    })
    assert "[routing]" in cfg
    assert 'allowed_providers = ["anthropic"]' in cfg
    assert "cost_aware = true" in cfg
    assert "verify_ensemble = true" in cfg
    assert "[planning]" in cfg and 'mode = "tree_of_thought"' in cfg
    assert "[context]" in cfg and "compact = true" in cfg
    assert "[reflexion]" in cfg and "enable = true" in cfg


def test_advanced_all_off_writes_no_sections(tmp_path, monkeypatch):
    cfg = _write(tmp_path, monkeypatch, dict.fromkeys(
        ["cost_aware", "verify_ensemble", "tree_of_thought",
         "compact_history", "reflexion", "enforce_quotas"], False,
    ))
    for section in ("[routing]", "[planning]", "[context]", "[reflexion]", "[quotas]"):
        assert section not in cfg


def test_kernel_modules_read_what_the_wizard_writes(tmp_path, monkeypatch):
    """End-to-end: write via the wizard, then the kernel sees each flag."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for env in ("MAVERICK_TREE_OF_THOUGHT", "MAVERICK_COMPACT_HISTORY",
                "MAVERICK_REFLEXION"):
        monkeypatch.delenv(env, raising=False)

    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    _write(cfg_dir, monkeypatch, {
        "tree_of_thought": True, "compact_history": True, "reflexion": True,
        "cost_aware": True, "verify_ensemble": True,
    })

    from maverick import context_compactor, reflexion, tree_of_thought
    assert tree_of_thought.enabled() is True
    assert context_compactor.enabled() is True
    assert reflexion.enabled() is True


def test_risk_proportional_verify_writes_and_is_read(tmp_path, monkeypatch):
    """Rule-6 loop: the wizard's risk-proportional toggle writes
    [verification] risk_proportional, and the kernel reads it back."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_RISK_PROPORTIONAL_VERIFY", raising=False)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = _write(cfg_dir, monkeypatch, {"risk_proportional_verify": True})
    assert "[verification]" in cfg
    assert "risk_proportional = true" in cfg

    from maverick.agent import _risk_proportional_verify_enabled
    assert _risk_proportional_verify_enabled() is True


def test_enforce_capabilities_writes_and_is_read(tmp_path, monkeypatch):
    """Rule-6 loop: the wizard's capability toggle writes [capabilities]
    enforce, and the kernel reads it back."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_ENFORCE_CAPABILITIES", raising=False)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = _write(cfg_dir, monkeypatch, {"enforce_capabilities": True})
    assert "[capabilities]" in cfg
    assert "enforce = true" in cfg

    from maverick.capability import capability_enforced
    assert capability_enforced() is True


def test_enforce_capabilities_reuses_existing_capabilities_table(tmp_path, monkeypatch):
    """The normal wizard path already writes [capabilities]; enabling
    enforcement must add to that table instead of emitting a duplicate TOML
    table that makes the entire config unreadable."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_ENFORCE_CAPABILITIES", raising=False)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    cfg = _write(
        cfg_dir,
        monkeypatch,
        {"enforce_capabilities": True},
        capabilities={"computer_use": False, "browser": False, "code_exec": False},
    )

    assert cfg.count("[capabilities]") == 1
    parsed = tomllib.loads(cfg)
    assert parsed["capabilities"] == {
        "computer_use": False,
        "browser": False,
        "code_exec": False,
        "enforce": True,
    }

    from maverick.capability import capability_enforced

    assert capability_enforced() is True
def test_tenant_by_user_writes_and_is_read(tmp_path, monkeypatch):
    """Rule-6 loop: the wizard's tenant toggle writes [tenancy] by_user, and
    the kernel reads it back."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_TENANT_BY_USER", raising=False)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = _write(cfg_dir, monkeypatch, {"tenant_by_user": True})
    assert "[tenancy]" in cfg
    assert "by_user = true" in cfg

    from maverick.paths import tenant_by_user_enabled
    assert tenant_by_user_enabled() is True


def test_enforce_quotas_writes_and_is_read(tmp_path, monkeypatch):
    """Rule-6 loop: the wizard's quota toggle writes [quotas] enforce + the
    daily caps, and the kernel reads them back."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for env in ("MAVERICK_QUOTA_ENFORCE", "MAVERICK_QUOTA_MAX_DOLLARS_PER_DAY",
                "MAVERICK_QUOTA_MAX_TOKENS_PER_DAY"):
        monkeypatch.delenv(env, raising=False)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = _write(cfg_dir, monkeypatch, {"enforce_quotas": True})
    assert "[quotas]" in cfg
    assert "enforce = true" in cfg
    assert "max_dollars_per_day = 25.0" in cfg
    assert "max_tokens_per_day = 5000000" in cfg

    from maverick.quotas import over_quota, quotas_enforced
    assert quotas_enforced() is True
    # Nothing recorded yet, so a fresh principal is under quota.
    assert over_quota("alice") is None


def test_oidc_writes_and_is_read(tmp_path, monkeypatch):
    """Rule-6 loop: the wizard's OIDC toggle writes a single [auth.oidc] table
    (enabled/issuer/audience/jwks_uri), the config round-trips through the TOML
    parser, and the kernel reads it back via maverick.oidc."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for env in ("MAVERICK_OIDC_ENABLED", "MAVERICK_OIDC_ISSUER",
                "MAVERICK_OIDC_AUDIENCE", "MAVERICK_OIDC_JWKS_URI",
                "MAVERICK_OIDC_ALGORITHMS"):
        monkeypatch.delenv(env, raising=False)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = _write(cfg_dir, monkeypatch, {"oidc": {
        "enabled": True,
        "issuer": "https://issuer.example.com",
        "audience": "maverick-client",
        "jwks_uri": "https://issuer.example.com/jwks",
    }})
    # Exactly one [auth.oidc] table -- no duplicate-table bug.
    assert cfg.count("[auth.oidc]") == 1
    # The whole config must still parse (a duplicate table would raise here).
    parsed = tomllib.loads(cfg)
    assert parsed["auth"]["oidc"] == {
        "enabled": True,
        "issuer": "https://issuer.example.com",
        "audience": "maverick-client",
        "jwks_uri": "https://issuer.example.com/jwks",
    }

    from maverick.oidc import load_oidc_config, oidc_enabled
    assert oidc_enabled() is True
    resolved = load_oidc_config()
    assert resolved.issuer == "https://issuer.example.com"
    assert resolved.audience == "maverick-client"
    assert resolved.jwks_uri == "https://issuer.example.com/jwks"
    # Allowlist defaults to asymmetric-only (the wizard doesn't surface it).
    assert resolved.algorithms == ["RS256", "ES256"]


def test_oidc_disabled_writes_no_section(tmp_path, monkeypatch):
    """Declining OIDC (the default) emits no [auth.oidc] table, and the kernel
    sees OIDC as off."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_OIDC_ENABLED", raising=False)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = _write(cfg_dir, monkeypatch, {"oidc": {"enabled": False}})
    assert "[auth.oidc]" not in cfg

    from maverick.oidc import oidc_enabled
    assert oidc_enabled() is False


def test_oidc_browser_login_writes_and_enables(tmp_path, monkeypatch):
    """Rule-6 loop: the wizard's optional browser-login fields land in
    [auth.oidc], round-trip through TOML, and the kernel sees login_enabled()."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for env in (
        "MAVERICK_OIDC_ENABLED", "MAVERICK_OIDC_ISSUER", "MAVERICK_OIDC_AUDIENCE",
        "MAVERICK_OIDC_JWKS_URI", "MAVERICK_OIDC_ALGORITHMS",
        "MAVERICK_OIDC_CLIENT_ID", "MAVERICK_OIDC_CLIENT_SECRET",
        "MAVERICK_OIDC_REDIRECT_URI", "MAVERICK_OIDC_SESSION_SECRET",
    ):
        monkeypatch.delenv(env, raising=False)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = _write(cfg_dir, monkeypatch, {"oidc": {
        "enabled": True,
        "issuer": "https://issuer.example.com",
        "audience": "maverick-client",
        "jwks_uri": "https://issuer.example.com/jwks",
        "client_id": "dash-client",
        "client_secret": "shhh",
        "redirect_uri": "https://dash.example.com/auth/callback",
        "session_secret": "a-long-random-session-secret",
    }})
    assert cfg.count("[auth.oidc]") == 1
    parsed = tomllib.loads(cfg)["auth"]["oidc"]
    assert parsed["client_id"] == "dash-client"
    assert parsed["redirect_uri"] == "https://dash.example.com/auth/callback"
    assert parsed["session_secret"] == "a-long-random-session-secret"

    from maverick.oidc import login_enabled
    assert login_enabled() is True


def test_oidc_bearer_only_omits_login_fields(tmp_path, monkeypatch):
    """A bearer-only OIDC config (no browser-login opt-in) writes none of the
    login keys, so the kernel leaves the login flow off."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for env in (
        "MAVERICK_OIDC_ENABLED", "MAVERICK_OIDC_CLIENT_ID",
        "MAVERICK_OIDC_SESSION_SECRET",
    ):
        monkeypatch.delenv(env, raising=False)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = _write(cfg_dir, monkeypatch, {"oidc": {
        "enabled": True,
        "issuer": "https://issuer.example.com",
        "audience": "maverick-client",
        "jwks_uri": "https://issuer.example.com/jwks",
    }})
    assert "client_id" not in cfg
    assert "session_secret" not in cfg

    from maverick.oidc import login_enabled, oidc_enabled
    assert oidc_enabled() is True
    assert login_enabled() is False


def test_enterprise_writes_and_is_read(tmp_path, monkeypatch):
    """Rule-6 loop: the wizard's enterprise toggle writes [enterprise] mode, and
    the kernel reads it back as enterprise_enabled()."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_ENTERPRISE", raising=False)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = _write(cfg_dir, monkeypatch, {"enterprise": True})
    assert "[enterprise]" in cfg
    assert "mode = true" in cfg

    from maverick.enterprise import enterprise_enabled
    assert enterprise_enabled() is True


def test_encrypt_at_rest_writes_and_is_read(tmp_path, monkeypatch):
    """Rule-6 loop: the wizard's encryption toggle writes [encryption] at_rest,
    and the kernel reads it back as at_rest_enabled()."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_ENCRYPT_AT_REST", raising=False)
    monkeypatch.delenv("MAVERICK_ENTERPRISE", raising=False)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = _write(cfg_dir, monkeypatch, {"encrypt_at_rest": True})
    assert "[encryption]" in cfg
    assert "at_rest = true" in cfg

    from maverick.crypto_at_rest import at_rest_enabled
    assert at_rest_enabled() is True


def test_audit_sign_writes_and_is_read(tmp_path, monkeypatch):
    """Rule-6 loop: the wizard's audit-signing toggle writes [audit] sign, and
    the kernel's signing resolver reads it back. This is the tamper-evidence
    control `maverick audit verify` and `maverick soc2` depend on."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_AUDIT_SIGN", raising=False)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = _write(cfg_dir, monkeypatch, {"audit_sign": True})
    assert "[audit]" in cfg
    assert "sign = true" in cfg

    from maverick.audit.writer import _resolve_signing
    # explicit=None -> falls through to MAVERICK_AUDIT_SIGN env (unset) ->
    # [audit] sign in the config the wizard just wrote.
    assert _resolve_signing(None) is True


def test_anonymous_logs_writes_and_is_read(tmp_path, monkeypatch):
    """Rule-6 loop: the wizard's anonymous-mode toggle writes [privacy]
    anonymous, and the kernel reads it back as anon_enabled() -- the PII-scrub
    over logs and audit events."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_ANON", raising=False)
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = _write(cfg_dir, monkeypatch, {"anonymous_logs": True})
    assert "[privacy]" in cfg
    assert "anonymous = true" in cfg

    from maverick.privacy import anon_enabled
    assert anon_enabled() is True
