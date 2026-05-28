"""Wizard env-file race fix — perms must be 0o600 from creation, not after."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch


def test_env_file_created_at_0600(tmp_path: Path, monkeypatch):
    """``write_text`` then ``chmod`` left a window where the file existed at 0644.

    The atomic ``os.open(..., O_CREAT|O_WRONLY|O_TRUNC, 0o600)`` path
    eliminates the race: the file's first ``stat`` after creation must
    already be 0o600.
    """
    monkeypatch.setattr("maverick_installer.wizard.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("maverick_installer.wizard.ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr("maverick_installer.wizard.CONFIG_FILE", tmp_path / "config.toml")

    # Patch the stat-on-create check by spying on the file inside write_config.
    observed_modes = []
    real_open = os.open

    def _watching_open(path, flags, mode=0o777):
        fd = real_open(path, flags, mode)
        try:
            observed_modes.append(stat.S_IMODE(os.stat(path).st_mode))
        except OSError:
            pass
        return fd

    with patch("maverick_installer.wizard.os.open", side_effect=_watching_open):
        from maverick_installer.wizard import write_config
        write_config(
            deployment="laptop",
            providers=["anthropic"],
            role_models={},
            channels={},
            safety={"profile": "balanced"},
            budget={"max_dollars": 5.0, "max_wall_seconds": 600, "max_tool_calls": 30},
            sandbox={"backend": "local", "workdir": "~/maverick-workspace"},
            keys={"ANTHROPIC_API_KEY": "sk-ant-test"},
            capabilities={},
        )

    # Both files (env + config) were created with 0o600.
    assert (tmp_path / ".env").exists()
    assert (tmp_path / "config.toml").exists()
    assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "config.toml").stat().st_mode) == 0o600
    # The atomic open observed 0o600 on first stat:
    assert observed_modes, "patched os.open never invoked"
    assert all(m == 0o600 for m in observed_modes), f"saw modes {observed_modes!r}"


def test_env_file_overwrites_existing(tmp_path: Path, monkeypatch):
    """Re-running the wizard with the same keys must overwrite cleanly at 0o600."""
    monkeypatch.setattr("maverick_installer.wizard.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("maverick_installer.wizard.ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr("maverick_installer.wizard.CONFIG_FILE", tmp_path / "config.toml")

    # Pre-create env at the wide mode the bug would leave it at.
    env = tmp_path / ".env"
    env.write_text("STALE=1\n")
    os.chmod(env, 0o644)

    from maverick_installer.wizard import write_config
    write_config(
        deployment="laptop",
        providers=["openai"],
        role_models={},
        channels={},
        safety={"profile": "balanced"},
        budget={"max_dollars": 5.0, "max_wall_seconds": 600, "max_tool_calls": 30},
        sandbox={"backend": "local", "workdir": "~/maverick-workspace"},
        keys={"OPENAI_API_KEY": "sk-new"},
        capabilities={},
    )

    assert "OPENAI_API_KEY=sk-new" in env.read_text()
    assert "STALE" not in env.read_text()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
