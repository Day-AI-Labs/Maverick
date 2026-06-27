"""Council pass: wizard parity with kernel features.

Confirms the eight new wizard steps emit correct TOML, the three new
channel adapters round-trip, and the `_safe_*` helpers replace the
crash-on-bad-input ``int()`` / ``float()`` calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover -- Py 3.10 CI matrix
    import tomli as tomllib  # type: ignore[no-redef]


# ---------- _safe_int / _safe_float ----------

def test_safe_int_handles_whitespace():
    from maverick_installer.wizard import _safe_int
    assert _safe_int("  42 ", default=0) == 42


def test_safe_int_falls_back_on_junk():
    from maverick_installer.wizard import _safe_int
    assert _safe_int("not-a-number", default=9) == 9
    assert _safe_int("", default=5) == 5
    assert _safe_int(None, default=7) == 7  # type: ignore[arg-type]


def test_safe_float_falls_back_on_junk():
    from maverick_installer.wizard import _safe_float
    assert _safe_float("xyz", default=1.5) == 1.5
    assert _safe_float("", default=2.5) == 2.5
    assert _safe_float("3.14", default=0) == 3.14


# ---------- wizard sections must be known to config-lint ----------

def test_wizard_written_sections_are_known_to_config_lint():
    """Every [section] block the wizard writes must be a section the runtime
    registry (migrate.KNOWN_SECTIONS, which config-lint sources) recognizes --
    otherwise an operator who enables a documented, wizard-offered feature gets
    a false "unknown config section" warning. Regression: [self_harness],
    [self_improvement], [dreaming], [fleet_memory], [rehearsal], [memory_guard],
    [actions], [domains], [fairness_monitor], [speculative] and [tax] all
    shipped unrecognized (the section-parity test only checked the two
    registries against each other, not against what the wizard writes)."""
    import re
    from pathlib import Path

    from maverick.migrate import KNOWN_SECTIONS
    from maverick_installer import wizard

    src = Path(wizard.__file__).read_text(encoding="utf-8")
    written = set(re.findall(
        r"""lines\.append\(\s*["']\[([a-z_][a-z0-9_]*)\]["']\s*\)""", src))
    assert written, "no [section] writes found in the wizard -- regex stale?"
    missing = sorted(written - set(KNOWN_SECTIONS))
    assert not missing, f"wizard writes sections config-lint will false-flag: {missing}"


# ---------- new CHANNELS entries ----------

def test_new_channels_added():
    from maverick_installer.wizard import CHANNELS
    ids = {c[0] for c in CHANNELS}
    assert "bluesky" in ids
    assert "mastodon" in ids
    assert "voice" in ids


def test_bluesky_channel_env_vars():
    from maverick_installer.wizard import CHANNELS
    spec = next(c for c in CHANNELS if c[0] == "bluesky")
    assert "BLUESKY_HANDLE" in spec[2]
    assert "BLUESKY_PASSWORD" in spec[2]


# ---------- new pick_*() functions exist ----------

@pytest.mark.parametrize("name", [
    "pick_web_search",
    "pick_mcp_servers",
    "pick_plugins",
    "pick_tool_acl",
    "pick_rate_limits",
    "pick_retention",
    "pick_persona",
    "pick_notifications",
    "pick_webhooks",
    "pick_self_learning",
    "pick_automation_import",
])
def test_new_pick_exists(name):
    from maverick_installer import wizard
    assert callable(getattr(wizard, name)), f"{name} missing"


def test_collect_api_keys_prompts_for_openai_compatible_base_url(monkeypatch):
    from maverick_installer import wizard

    prompts: list[str] = []
    answers = {
        "OPENAI_COMPATIBLE_API_KEY": "sk-compatible",
        "OPENAI_COMPATIBLE_BASE_URL": "http://localhost:1234/v1",
    }

    def fake_secret(prompt: str, *args, **kwargs):
        prompts.append(prompt)
        for env_name, value in answers.items():
            if env_name in prompt:
                return value
        return ""

    monkeypatch.setattr(wizard, "_q_secret", fake_secret)
    keys = wizard.collect_api_keys(["openai_compatible"], set())

    assert keys == answers
    assert any("OPENAI_COMPATIBLE_API_KEY" in prompt for prompt in prompts)
    assert any("OPENAI_COMPATIBLE_BASE_URL" in prompt for prompt in prompts)


# ---------- write_config emits new TOML sections ----------

def _write_full_config(tmp_path: Path, monkeypatch, **overrides) -> dict:
    from maverick_installer import wizard
    monkeypatch.setattr(wizard, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(wizard, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(wizard, "ENV_FILE", tmp_path / ".env")
    base = dict(
        providers=["anthropic"],
        role_models={},
        channels={},
        safety={"profile": "balanced", "block_threshold": "high",
                "scan_input": True, "scan_tool_calls": True, "scan_output": True},
        budget={"max_dollars": 5.0, "max_wall_seconds": 3600.0, "max_tool_calls": 500},
        sandbox={"backend": "local", "workdir": str(tmp_path / "ws"), "timeout": 60},
        keys={},
        capabilities={"computer_use": False, "browser": False},
    )
    base.update(overrides)
    wizard.write_config(**base)
    body = (tmp_path / "config.toml").read_text()
    return tomllib.loads(body)


def test_write_config_emits_mcp_servers(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        mcp_servers={"fs": {"command": "npx", "args": ["-y", "x"]}},
    )
    assert parsed["mcp_servers"]["fs"]["command"] == "npx"
    assert parsed["mcp_servers"]["fs"]["args"] == ["-y", "x"]


def test_write_config_emits_mcp_registries(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        mcp_registries=["https://registry.example.com/catalog",
                        "https://internal.acme/catalog"],
    )
    assert parsed["mcp_registries"]["indexes"] == [
        "https://registry.example.com/catalog", "https://internal.acme/catalog"]


def test_write_config_omits_mcp_registries_by_default(tmp_path: Path, monkeypatch):
    # No override -> no [mcp_registries] section (discovery uses the built-in
    # default index, so the config stays minimal).
    parsed = _write_full_config(tmp_path, monkeypatch)
    assert "mcp_registries" not in parsed


def test_write_config_emits_template_registries(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        template_registries=["https://templates.example.com/catalog"],
    )
    assert parsed["template_registries"]["indexes"] == [
        "https://templates.example.com/catalog"]
    # default: omitted
    assert "template_registries" not in _write_full_config(tmp_path, monkeypatch)


def test_write_config_emits_plugins(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch, plugins=["weather", "github-issues"],
    )
    assert parsed["plugins"]["enabled"] == ["weather", "github-issues"]


def test_write_config_emits_self_learning(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        self_learning={
            "enable": True, "preflight": True, "create_tools": True,
            "max_acquisitions": 3,
        },
    )
    assert parsed["self_learning"]["enable"] is True
    assert parsed["self_learning"]["create_tools"] is True
    assert parsed["self_learning"]["max_acquisitions"] == 3
    # The retired add_mcp_servers knob is no longer written.
    assert "add_mcp_servers" not in parsed["self_learning"]


def test_write_config_emits_durable_when_enabled(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        durable={"enabled": True, "keep_last": 5},
    )
    assert parsed["durable"]["enabled"] is True
    assert parsed["durable"]["keep_last"] == 5


def test_write_config_omits_durable_when_disabled(tmp_path: Path, monkeypatch):
    # Off by default: a disabled durable dict writes no [durable] section,
    # keeping the config minimal (the kernel defaults to off anyway).
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        durable={"enabled": False},
    )
    assert "durable" not in parsed


def test_write_config_roundtrips_backslash_paths_and_allowlist(tmp_path: Path, monkeypatch):
    """A Windows backslash workdir must round-trip (escaped TOML basic string)
    and a channel allowed_user_ids must emit as an ARRAY. Regression: the raw
    f'{k} = "{v}"' emit turned C:\\Users... into an invalid \\U escape (config
    unreadable on Windows) and rendered a list as a quoted string."""
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        sandbox={"backend": "local", "workdir": r"C:\Users\me\maverick ws", "timeout": 60},
        channels={"discord": {
            "enabled": True,
            "bot_token": "${DISCORD_BOT_TOKEN}",
            "allowed_user_ids": ["111", "222"],
        }},
    )
    # Round-trips without TOMLDecodeError and preserves the backslashes.
    assert parsed["sandbox"]["workdir"] == r"C:\Users\me\maverick ws"
    # The allowlist is a TOML array, not a stringified list.
    assert parsed["channels"]["discord"]["allowed_user_ids"] == ["111", "222"]


def test_write_config_emits_tool_acl(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        tool_acl={
            "denied_tools": ["computer"],
            "channels": {"telegram": {"denied_tools": ["shell"]}},
        },
    )
    assert parsed["security"]["denied_tools"] == ["computer"]
    assert parsed["security"]["channels"]["telegram"]["denied_tools"] == ["shell"]


def test_write_config_emits_rate_limits_with_glob(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        rate_limits={"web_search": "10/60", "mcp_*": "60/60"},
    )
    assert parsed["rate_limits"]["web_search"] == "10/60"
    # Glob keys must be quoted in TOML.
    assert parsed["rate_limits"]["mcp_*"] == "60/60"


def test_write_config_emits_retention(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        retention={"audit_days": 90, "episodes_days": 365, "events_days": 180},
    )
    assert parsed["retention"]["audit_days"] == 90
    assert parsed["retention"]["episodes_days"] == 365


def test_write_config_emits_persona(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        persona={"name": "Hawk", "style": "concise"},
    )
    assert parsed["persona"]["name"] == "Hawk"
    assert parsed["persona"]["style"] == "concise"


def test_write_config_emits_notifications(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        notifications={"backend": "ntfy", "topic": "alerts"},
    )
    assert parsed["notifications"]["backend"] == "ntfy"
    assert parsed["notifications"]["topic"] == "alerts"


def test_write_config_emits_webhooks(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        webhooks={"outbound": ["https://a.example", "https://b.example"],
                  "secret": "${MAVERICK_WEBHOOK_SECRET}"},
    )
    assert parsed["webhooks"]["outbound"] == ["https://a.example", "https://b.example"]
    assert parsed["webhooks"]["secret"] == "${MAVERICK_WEBHOOK_SECRET}"


def test_write_config_emits_deliverable_handoff(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        deliverables={"handoff_webhook": "https://sor.example/ingest"},
    )
    assert parsed["deliverables"]["handoff_webhook"] == "https://sor.example/ingest"


def test_write_config_emits_personas(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        personas={"default": ["fpa_analyst", "treasurer"]},
    )
    assert parsed["personas"]["default"] == ["fpa_analyst", "treasurer"]


def test_write_config_emits_a2a(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch, a2a={"enabled": True},
    )
    assert parsed["a2a"]["enabled"] is True


def test_write_config_emits_web_search_capability(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch, web_search_enabled=True,
    )
    assert parsed["capabilities"]["web_search"] is True


def test_write_config_omits_empty_optional_sections(tmp_path: Path, monkeypatch):
    """Unspecified optionals should not emit empty sections."""
    parsed = _write_full_config(tmp_path, monkeypatch)
    for sec in ("mcp_servers", "plugins", "security", "rate_limits",
                "retention", "persona", "notifications", "webhooks", "a2a",
                "self_learning"):
        assert sec not in parsed, f"{sec} should be absent"


# ---------- pick_*() functions return safe defaults when declined ----------

class _StubQ:
    """Mock the questionary primitives — every prompt returns 'no'/empty."""

    def __init__(self, monkeypatch):
        monkeypatch.setattr(
            "maverick_installer.wizard._q_confirm",
            lambda *a, **kw: False,
        )
        monkeypatch.setattr(
            "maverick_installer.wizard._q_text",
            lambda *a, **kw: kw.get("default", ""),
        )
        monkeypatch.setattr(
            "maverick_installer.wizard._q_select",
            lambda *a, **kw: kw.get("default", a[1][0]) if len(a) > 1 else "",
        )
        monkeypatch.setattr(
            "maverick_installer.wizard._q_checkbox",
            lambda *a, **kw: kw.get("default", []),
        )


def test_pick_mcp_servers_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_mcp_servers
    assert pick_mcp_servers() == {}


def test_pick_plugins_returns_empty_when_no_entry_points(monkeypatch):
    _StubQ(monkeypatch)
    # Force empty entry_points discovery.
    import maverick_installer.wizard as w
    real_plugins = sys.modules.get("maverick.plugins")
    try:
        # Remove module so the import in pick_plugins re-imports / fails.
        sys.modules.pop("maverick.plugins", None)
        out = w.pick_plugins()
        assert out == []
    finally:
        if real_plugins:
            sys.modules["maverick.plugins"] = real_plugins


def test_pick_tool_acl_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_tool_acl
    assert pick_tool_acl(channels={}) == {}


def test_pick_rate_limits_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_rate_limits
    assert pick_rate_limits(channels={}) == {}


def test_pick_retention_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_retention
    assert pick_retention() == {}


def test_pick_persona_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_persona
    assert pick_persona() == {}


def test_pick_a2a_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_a2a
    assert pick_a2a() == ({}, [])


def test_pick_notifications_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_notifications
    cfg, envs = pick_notifications()
    assert cfg == {}
    assert envs == []


def test_pick_webhooks_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_webhooks
    cfg, envs = pick_webhooks()
    assert cfg == {}
    assert envs == []


def test_pick_web_search_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_web_search
    enabled, envs = pick_web_search()
    assert enabled is False
    assert envs == []


# ---------- new advanced knobs (build-wave feature toggles) ----------

def test_write_config_emits_tools_output_cache(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch, advanced={"output_cache": True},
    )
    assert parsed["tools"]["output_cache"] is True


def test_write_config_tools_block_coexists(tmp_path: Path, monkeypatch):
    # deferred_loading + output_cache + hardware_sensors share a single [tools] table.
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        advanced={
            "deferred_tools": True,
            "output_cache": True,
            "hardware_sensors": True,
        },
    )
    assert parsed["tools"]["deferred_loading"] is True
    assert parsed["tools"]["output_cache"] is True
    assert parsed["tools"]["hardware_sensors"] is True


def test_write_config_emits_consequence_when_enabled(tmp_path: Path, monkeypatch):
    # The Consequence Engine had a config knob + kernel reader but no wizard step,
    # so it was unreachable through the installer. Pin that it now emits.
    parsed = _write_full_config(
        tmp_path, monkeypatch, advanced={"consequence": True},
    )
    assert parsed["consequence"]["enable"] is True


def test_write_config_omits_consequence_by_default(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(tmp_path, monkeypatch, advanced={"consequence": False})
    assert "consequence" not in parsed


def test_write_config_emits_routing_energy_aware(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch, advanced={"energy_aware": True},
    )
    assert parsed["routing"]["energy_aware"] is True
    assert parsed["routing"]["allowed_providers"] == ["anthropic"]


def test_write_config_emits_system_local_first(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch, advanced={"local_first": True},
    )
    assert parsed["system"]["local_first"] is True
    assert "local_first" not in parsed


def test_write_config_emits_local_first_model_for_local_provider(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch, providers=["anthropic", "ollama"],
        advanced={"local_first": True},
    )
    assert parsed["system"]["local_first"] is True
    assert parsed["local_first"]["model"].startswith("ollama:")


def test_write_config_emits_self_learning_distill_local(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        self_learning={"enable": True, "distill_local": True},
    )
    assert parsed["self_learning"]["distill_local"] is True


def test_write_config_omits_new_knobs_when_off(tmp_path: Path, monkeypatch):
    # Empty advanced -> no [system], no energy-aware-only [routing], no [tools].
    parsed = _write_full_config(tmp_path, monkeypatch, advanced={})
    assert "system" not in parsed
    assert "routing" not in parsed
    assert "tools" not in parsed


def test_pick_advanced_includes_new_toggles(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_advanced
    adv = pick_advanced()
    for key in ("output_cache", "local_first", "energy_aware", "hardware_sensors"):
        assert key in adv, f"{key} missing from pick_advanced()"


def test_pick_self_learning_includes_distill_local(monkeypatch):
    # Force every confirm to True so the enabled branch runs.
    monkeypatch.setattr("maverick_installer.wizard._q_confirm", lambda *a, **kw: True)
    from maverick_installer.wizard import pick_self_learning
    result = pick_self_learning()
    assert result["enable"] is True
    assert result["distill_local"] is True


# ---------- finance suite wizard step (finance-agent-suite §8) ----------

def test_pick_finance_skipped(monkeypatch):
    _StubQ(monkeypatch)
    from maverick_installer.wizard import pick_finance
    assert pick_finance() == {"enable": False}


def test_write_config_emits_finance_governance(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        finance={"enable": True, "regimes": ["sox", "gaap"],
                 "require_human_above": 5000.0, "deny_above": 50000.0,
                 "sdn_path": "/etc/ofac/sdn.txt"},
    )
    assert parsed["governance"]["require_human_min_risk"] == "high"
    assert parsed["governance"]["require_human_above"]["*"] == 5000.0
    assert parsed["governance"]["deny_above"]["*"] == 50000.0
    assert parsed["finance"]["regimes"] == ["sox", "gaap"]
    assert parsed["screening"]["sdn_path"] == "/etc/ofac/sdn.txt"


def test_write_config_emits_require_fresh_human_approval(tmp_path: Path, monkeypatch):
    # Opt-in per-action oversight: the [governance] scalar is emitted only when
    # the wizard pick set it.
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        finance={"enable": True, "regimes": ["sox"], "require_human_above": 5000.0,
                 "deny_above": 0, "require_fresh_human_approval": True, "sdn_path": ""},
    )
    assert parsed["governance"]["require_fresh_human_approval"] is True
    # Absent by default (backwards compatible).
    parsed2 = _write_full_config(
        tmp_path, monkeypatch,
        finance={"enable": True, "regimes": ["sox"], "require_human_above": 5000.0,
                 "deny_above": 0, "sdn_path": ""},
    )
    assert "require_fresh_human_approval" not in parsed2["governance"]


def test_write_config_omits_finance_when_off(tmp_path: Path, monkeypatch):
    parsed = _write_full_config(tmp_path, monkeypatch)
    assert "finance" not in parsed
    assert "governance" not in parsed
    assert "screening" not in parsed


def test_write_config_finance_no_thresholds(tmp_path: Path, monkeypatch):
    # require_human_above=0 means "pause all" -> rely on require_human_min_risk,
    # no [governance.require_human_above] sub-table emitted.
    parsed = _write_full_config(
        tmp_path, monkeypatch,
        finance={"enable": True, "regimes": ["sox"],
                 "require_human_above": 0, "deny_above": 0, "sdn_path": ""},
    )
    assert parsed["governance"]["require_human_min_risk"] == "high"
    assert "require_human_above" not in parsed["governance"]
    assert "screening" not in parsed
