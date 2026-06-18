"""maverick support — a redacted diagnostics bundle. Secrets must never appear
in it; the core sections must always be present."""
from __future__ import annotations

import json

from maverick import support_bundle


def test_redacts_secret_named_keys():
    src = {
        "providers": {"anthropic": {"api_key": "sk-ant-SECRETVALUE"}},  # pragma: allowlist secret
        "federation": {"peers": [{"name": "vega", "token": "TOPSECRETTOKEN"}]},  # pragma: allowlist secret
        "models": {"orchestrator": "anthropic:claude-opus-4-8"},  # kept
    }
    out = support_bundle._redact(src)
    assert out["providers"]["anthropic"]["api_key"] == "[REDACTED]"
    assert out["federation"]["peers"][0]["token"] == "[REDACTED]"
    assert out["models"]["orchestrator"] == "anthropic:claude-opus-4-8"
    assert "SECRETVALUE" not in json.dumps(out)
    assert "TOPSECRETTOKEN" not in json.dumps(out)


def test_collect_has_core_sections_and_is_json():
    bundle = support_bundle.collect()
    for key in ("versions", "runtime", "readiness", "providers",
                "recent_failures", "config_redacted", "generated_at"):
        assert key in bundle
    # The whole bundle must serialize (no stray non-JSON objects).
    json.dumps(bundle, default=str)


def test_collect_config_is_redacted(monkeypatch):
    monkeypatch.setattr(
        "maverick.config.load_config",
        lambda: {"providers": {"openai": {"api_key": "sk-LEAKME"}}})  # pragma: allowlist secret
    bundle = support_bundle.collect()
    assert "sk-LEAKME" not in json.dumps(bundle["config_redacted"], default=str)


def test_cli_support_writes_redacted_file(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from maverick.cli import main
    monkeypatch.setattr(
        "maverick.config.load_config",
        lambda: {"providers": {"openai": {"api_key": "sk-LEAKME"}}})  # pragma: allowlist secret
    out = tmp_path / "bundle.json"
    r = CliRunner().invoke(main, ["support", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert out.exists()
    text = out.read_text()
    assert "sk-LEAKME" not in text
    assert json.loads(text)["versions"]  # parseable + populated


def test_cli_support_stdout():
    from click.testing import CliRunner
    from maverick.cli import main
    r = CliRunner().invoke(main, ["support"])
    assert r.exit_code == 0
    assert json.loads(r.output)["runtime"]["python"]
