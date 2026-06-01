"""The wizard's 'Advanced reasoning' step writes the kernel's opt-in config
sections, and the keys it writes are exactly the ones the kernel modules
read (the rule-6 integrity check: a wizard toggle must actually reach the
feature)."""
from __future__ import annotations


def _write(cfg_dir, monkeypatch, advanced):
    monkeypatch.setattr("maverick_installer.wizard.CONFIG_DIR", cfg_dir)
    monkeypatch.setattr("maverick_installer.wizard.ENV_FILE", cfg_dir / ".env")
    monkeypatch.setattr("maverick_installer.wizard.CONFIG_FILE", cfg_dir / "config.toml")
    from maverick_installer.wizard import write_config
    write_config(
        deployment="laptop", providers=["anthropic"], role_models={},
        channels={}, safety={"profile": "balanced"},
        budget={"max_dollars": 5.0, "max_wall_seconds": 600, "max_tool_calls": 30},
        sandbox={"backend": "local", "workdir": "~/ws"},
        keys={"ANTHROPIC_API_KEY": "x"}, capabilities={}, advanced=advanced,
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
         "compact_history", "reflexion"], False,
    ))
    for section in ("[routing]", "[planning]", "[context]", "[reflexion]"):
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
