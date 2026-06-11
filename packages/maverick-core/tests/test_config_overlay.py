from __future__ import annotations

from maverick.config import get_sandbox, load_config


def test_config_overlay_deep_merges_without_replacing_operator_config(monkeypatch, tmp_path):
    base = tmp_path / "config.toml"
    base.write_text(
        """
[sandbox]
backend = "docker"
timeout = 42

[budget]
max_dollars = 0.25

[search]
enable = false
n = 1
""".strip(),
        encoding="utf-8",
    )
    overlay = tmp_path / "overlay.toml"
    overlay.write_text(
        """
[search]
enable = true
n = 5

[adaptive_compute]
enable = true
low_uncertainty = 0.2
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("MAVERICK_CONFIG", str(base))
    monkeypatch.setenv("MAVERICK_CONFIG_OVERLAY", str(overlay))

    cfg = load_config()

    assert cfg["sandbox"] == {"backend": "docker", "timeout": 42}
    assert cfg["budget"] == {"max_dollars": 0.25}
    assert cfg["search"] == {"enable": True, "n": 5}
    assert cfg["adaptive_compute"] == {"enable": True, "low_uncertainty": 0.2}
    assert get_sandbox()["backend"] == "docker"


def test_explicit_load_config_path_ignores_environment_overlay(monkeypatch, tmp_path):
    base = tmp_path / "config.toml"
    base.write_text('[search]\nn = 1\n', encoding="utf-8")
    overlay = tmp_path / "overlay.toml"
    overlay.write_text('[search]\nn = 5\n', encoding="utf-8")
    monkeypatch.setenv("MAVERICK_CONFIG_OVERLAY", str(overlay))

    assert load_config(base) == {"search": {"n": 1}}
