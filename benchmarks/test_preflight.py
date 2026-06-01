"""Tier 0 (Wave 11): tests for the pre-flight checker.

The pre-flight is the last guard before a paid run. We need to confirm
each check FIRES on the failure mode it's supposed to catch, and PASSES
on the happy path. Otherwise a future refactor could silently turn a
check into a no-op.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_preflight():
    p = Path(__file__).resolve().parent / "preflight.py"
    spec = importlib.util.spec_from_file_location("benchmarks_preflight", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["benchmarks_preflight"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- Model ID validation ----


def test_check_model_ids_passes_on_default_roles(monkeypatch):
    """All ROLE_MODELS entries must resolve to MODEL_PRICES table."""
    pf = _load_preflight()
    # Clear any env overrides that could trip the check.
    for k in list(__import__("os").environ):
        if k.startswith("MAVERICK_MODEL_OVERRIDE_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("MAVERICK_BON_LADDER", raising=False)
    assert pf.check_model_ids() is True


def test_check_model_ids_fails_on_typo_override(monkeypatch):
    """A typo'd MAVERICK_MODEL_OVERRIDE_ORCHESTRATOR is exactly the bug
    this check exists to catch."""
    pf = _load_preflight()
    monkeypatch.setenv(
        "MAVERICK_MODEL_OVERRIDE_ORCHESTRATOR", "claude-opus-4.7",
    )  # dot instead of dash
    assert pf.check_model_ids() is False


def test_check_model_ids_fails_on_bad_bon_ladder(monkeypatch):
    pf = _load_preflight()
    monkeypatch.setenv(
        "MAVERICK_BON_LADDER",
        "claude-sonnet-4-6:0.3,nonexistent-model:0.5",
    )
    assert pf.check_model_ids() is False


def test_check_model_ids_accepts_provider_prefix(monkeypatch):
    """`anthropic:claude-sonnet-4-6` should strip the provider before
    looking up in MODEL_PRICES."""
    pf = _load_preflight()
    monkeypatch.setenv(
        "MAVERICK_MODEL_OVERRIDE_CODER", "anthropic:claude-sonnet-4-6",
    )
    assert pf.check_model_ids() is True


# ---- Disk space ----


def test_check_disk_space_passes_on_low_threshold():
    pf = _load_preflight()
    # 1MB threshold -- always passes.
    assert pf.check_disk_space(0.001) is True


def test_check_disk_space_fails_on_petabyte_threshold():
    pf = _load_preflight()
    # 1PB threshold -- guaranteed fail unless someone's testing on
    # a literal data centre.
    assert pf.check_disk_space(1024 * 1024) is False


# ---- API key ----


def test_check_api_key_fails_when_unset(monkeypatch):
    pf = _load_preflight()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert pf.check_api_key() is False


# ---- Wave 11 env (warnings only) ----


def test_check_wave11_env_returns_true_when_all_set(monkeypatch):
    pf = _load_preflight()
    monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
    monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "1")
    monkeypatch.setenv("MAVERICK_USE_SKILLS", "0")
    monkeypatch.setenv("MAVERICK_MAX_STEPS", "25")
    monkeypatch.setenv("MAVERICK_INSTANCE_HARD_CAP", "3.0")
    assert pf.check_wave11_env() is True


def test_check_wave11_env_returns_true_when_unset(monkeypatch):
    """Missing env vars are warnings, NOT failures."""
    pf = _load_preflight()
    for k in ("MAVERICK_CODING_MODE", "MAVERICK_BENCHMARK_OPAQUE",
              "MAVERICK_USE_SKILLS", "MAVERICK_MAX_STEPS",
              "MAVERICK_INSTANCE_HARD_CAP", "MAVERICK_BEST_OF_N"):
        monkeypatch.delenv(k, raising=False)
    # Returns True (no FAILs); warnings print to stdout.
    assert pf.check_wave11_env() is True


def test_check_wave11_env_non_integer_bon_is_warning_only(monkeypatch):
    pf = _load_preflight()
    monkeypatch.setenv("MAVERICK_BEST_OF_N", "bogus")
    assert pf.check_wave11_env() is True


# ---- Config stale-override check ----


def test_check_config_no_stale_overrides_passes_on_no_config(
    monkeypatch, tmp_path,
):
    """No ~/.maverick/config.toml → silent pass."""
    pf = _load_preflight()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows fallback
    assert pf.check_config_no_stale_overrides() is True


# ---- Python version ----


def test_check_python_version_passes_on_supported():
    pf = _load_preflight()
    assert pf.check_python_version() is True


# ---- Integration: main() runs end-to-end with skips ----


def test_main_with_all_skips_succeeds(monkeypatch, capsys):
    """Smoke: with --skip-api --skip-network and tiny disk, main()
    should exit 0 if model IDs are sane."""
    pf = _load_preflight()
    monkeypatch.setattr(sys, "argv", [
        "preflight.py", "--skip-api", "--skip-network", "--min-disk-gb", "0.001",
    ])
    # Clear typo'd overrides.
    for k in list(__import__("os").environ):
        if k.startswith("MAVERICK_MODEL_OVERRIDE_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("MAVERICK_BON_LADDER", raising=False)
    exit_code = pf.main()
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "All required checks passed" in out


def test_main_fails_on_bad_override(monkeypatch, capsys):
    pf = _load_preflight()
    monkeypatch.setenv("MAVERICK_MODEL_OVERRIDE_CODER", "garbled-model-id")
    monkeypatch.setattr(sys, "argv", [
        "preflight.py", "--skip-api", "--skip-network", "--min-disk-gb", "0.001",
    ])
    exit_code = pf.main()
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "FAIL" in out
