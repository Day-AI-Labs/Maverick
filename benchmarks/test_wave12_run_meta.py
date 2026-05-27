"""Wave 12 (council F16): run_meta.json reproducibility provenance."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_sb():
    p = Path(__file__).resolve().parent / "swe_bench.py"
    spec = importlib.util.spec_from_file_location("benchmarks_swe_bench", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["benchmarks_swe_bench"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestRunMetaWriter:
    def test_writes_expected_fields(self, tmp_path):
        sb = _load_sb()
        manifest = tmp_path / "m.txt"
        manifest.write_text("instance_a\ninstance_b\n", encoding="utf-8")
        args = SimpleNamespace(
            instances=manifest,
            pipelines="maverick",
            out=tmp_path / "results.csv",
            adoption_tripwire=None,
            num_workers=1,
            worker_index=0,
        )
        meta_path = sb._write_run_meta(tmp_path, args, manifest)
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        # Required fields for reproducibility.
        for key in (
            "started_at",
            "started_at_iso",
            "maverick_git_sha",
            "manifest_sha256",
            "pip_freeze",
            "anthropic_sdk_version",
            "env_snapshot",
            "cli_args",
            "host",
        ):
            assert key in meta, f"missing reproducibility field {key!r}"

    def test_manifest_sha_changes_with_content(self, tmp_path):
        sb = _load_sb()
        manifest = tmp_path / "m.txt"
        manifest.write_text("a\n", encoding="utf-8")
        args = SimpleNamespace(instances=manifest, out=tmp_path / "r.csv")

        sb._write_run_meta(tmp_path, args, manifest)
        meta1 = json.loads(
            (tmp_path / "run_meta.json").read_text(encoding="utf-8")
        )

        manifest.write_text("a\nb\n", encoding="utf-8")
        sb._write_run_meta(tmp_path, args, manifest)
        meta2 = json.loads(
            (tmp_path / "run_meta.json").read_text(encoding="utf-8")
        )

        assert meta1["manifest_sha256"] != meta2["manifest_sha256"], (
            "manifest SHA must change when the file changes"
        )

    def test_api_keys_redacted(self, tmp_path, monkeypatch):
        sb = _load_sb()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        manifest = tmp_path / "m.txt"
        manifest.write_text("a\n", encoding="utf-8")
        args = SimpleNamespace(instances=manifest, out=tmp_path / "r.csv")
        sb._write_run_meta(tmp_path, args, manifest)
        meta = json.loads(
            (tmp_path / "run_meta.json").read_text(encoding="utf-8")
        )
        env = meta["env_snapshot"]
        # Secrets redacted...
        assert env.get("ANTHROPIC_API_KEY") == "REDACTED", (
            "API keys MUST be redacted from run_meta to avoid checking "
            "credentials into post-mortems / public bug reports"
        )
        # ...non-secret env vars preserved.
        assert env.get("MAVERICK_CODING_MODE") == "1"

    def test_additional_secret_names_redacted(self, tmp_path, monkeypatch):
        sb = _load_sb()
        monkeypatch.setenv("MAVERICK_PASSWORD", "correct-horse-battery-staple")
        monkeypatch.setenv("ANTHROPIC_CREDENTIALS", "client_id:client_secret")
        monkeypatch.setenv("MAVERICK_AUTH_URL", "https://ci-user:ci-pass@example.internal/api")
        manifest = tmp_path / "m.txt"
        manifest.write_text("a\n", encoding="utf-8")
        args = SimpleNamespace(instances=manifest, out=tmp_path / "r.csv")
        sb._write_run_meta(tmp_path, args, manifest)
        env = json.loads((tmp_path / "run_meta.json").read_text(encoding="utf-8"))["env_snapshot"]
        assert env.get("MAVERICK_PASSWORD") == "REDACTED"
        assert env.get("ANTHROPIC_CREDENTIALS") == "REDACTED"
        assert env.get("MAVERICK_AUTH_URL") == "REDACTED"

    def test_pip_freeze_authenticated_urls_redacted(self, tmp_path, monkeypatch):
        sb = _load_sb()

        class _R:
            returncode = 0
            stdout = (
                "privatepkg @ git+https://user:ghp_FAKESECRET@example.internal/org/privatepkg.git@main\n"
            )

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
        manifest = tmp_path / "m.txt"
        manifest.write_text("a\n", encoding="utf-8")
        args = SimpleNamespace(instances=manifest, out=tmp_path / "r.csv")
        sb._write_run_meta(tmp_path, args, manifest)
        pip_freeze = json.loads((tmp_path / "run_meta.json").read_text(encoding="utf-8"))["pip_freeze"]
        assert "user:ghp_FAKESECRET@" not in pip_freeze
        assert "https://REDACTED@" in pip_freeze
