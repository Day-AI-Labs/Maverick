"""Wave 10: SWE-bench Pro final pre-flight fixes.

Covers the bugs surfaced by the 20-agent extreme council + the code
reviewer agent's verified defect list. Each test pins one specific
fix so regressions are obvious.
"""
from __future__ import annotations

# ---- D2: extract_unified_diff supports `diff --git` headers + renames ----

class TestExtractUnifiedDiffGitFormat:
    def test_diff_git_prefix_before_minus_plus_passes(self):
        from maverick.coding_mode import extract_unified_diff
        text = (
            "diff --git a/foo.py b/foo.py\n"
            "index abc..def 100644\n"
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
        )
        out = extract_unified_diff(text)
        assert out is not None
        assert "diff --git a/foo.py b/foo.py" in out
        assert "+new" in out

    def test_rename_only_diff_returns_diff(self):
        from maverick.coding_mode import extract_unified_diff
        text = (
            "diff --git a/old.py b/new.py\n"
            "similarity index 100%\n"
            "rename from old.py\n"
            "rename to new.py\n"
        )
        out = extract_unified_diff(text)
        # Rename-only diffs have no @@ hunks; Wave 10 accepts them
        # because we now anchor on `diff --git` as an alternative start.
        assert out is not None
        assert "rename from old.py" in out

    def test_crlf_input_is_normalised(self):
        from maverick.coding_mode import extract_unified_diff
        text = (
            "--- a/foo.py\r\n+++ b/foo.py\r\n@@ -1 +1 @@\r\n-old\r\n+new\r\n"
        )
        out = extract_unified_diff(text)
        assert out is not None
        assert "\r" not in out
        assert "+new" in out


# ---- C4: validate_patch accepts new-file diffs ----

class TestValidatePatchNewFile:
    def test_dev_null_minus_passes_header_check(self, tmp_path):
        # Construct a tiny git repo so the function can attempt git apply.
        import subprocess

        from maverick.coding_mode import validate_patch
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "commit.gpgsign", "false"], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
        # Make an initial commit so HEAD exists.
        (tmp_path / "seed.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "seed.py"], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-q", "-m", "seed"],
            check=True,
        )
        new_file_patch = (
            "diff --git a/new.py b/new.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+hello\n"
            "+world\n"
        )
        v = validate_patch(new_file_patch, tmp_path)
        # We don't assert valid=True (git's --check is strict) but
        # we DO assert the header check no longer rejects new-file
        # diffs at the early-validate stage.
        assert "missing" not in v.reason


# ---- D5: sandbox.exec accepts a per-call timeout kwarg ----

class TestSandboxExecTimeout:
    def test_local_backend_accepts_timeout_kwarg(self, tmp_path):
        from maverick.sandbox import LocalBackend
        sb = LocalBackend(workdir=tmp_path, timeout=1.0)
        # A quick command should succeed even when we hand it a long timeout.
        r = sb.exec("echo hello", timeout=10.0)
        assert r.exit_code == 0
        assert "hello" in r.stdout

    def test_local_backend_timeout_kwarg_overrides_self_timeout(self, tmp_path):
        from maverick.sandbox import LocalBackend
        # self.timeout would be 0.1s, but the call passes 5s, so a
        # 0.5s sleep completes successfully (no TIMEOUT).
        # Wave 11: use python -c for cross-platform sleep (Unix `sleep`
        # is not available on Windows).
        sb = LocalBackend(workdir=tmp_path, timeout=0.1)
        import sys
        py = sys.executable.replace("\\", "/")  # quote-friendly on Windows
        r = sb.exec(
            f'"{py}" -c "import time; time.sleep(0.5); print(\'done\')"',
            timeout=5.0,
        )
        assert r.exit_code == 0
        assert "done" in r.stdout


# ---- D4: detect_test_runner takes language hint ----

class TestDetectRunnerLanguageHint:
    def test_jest_monorepo_with_pyproject_picks_jest_when_hinted(self, tmp_path):
        from maverick.coding_mode import detect_test_runner
        (tmp_path / "pyproject.toml").write_text("[tool.pre-commit]\n")
        (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}')
        # No hint: order-based pick (pytest wins, wrong for JS instance).
        assert detect_test_runner(tmp_path) == "pytest"
        # With language=javascript hint: correct pick.
        assert detect_test_runner(tmp_path, language="javascript") == "jest"

    def test_python_hint_in_pure_python_repo_still_picks_pytest(self, tmp_path):
        from maverick.coding_mode import detect_test_runner
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        assert detect_test_runner(tmp_path, language="python") == "pytest"

    def test_java_hint_with_gradle_markers_picks_gradle(self, tmp_path):
        from maverick.coding_mode import detect_test_runner
        (tmp_path / "build.gradle").write_text("plugins {}\n")
        assert detect_test_runner(tmp_path, language="java") == "gradle"


# ---- D1: MAVERICK_TEMPERATURE is read by the Anthropic provider ----

class TestTemperatureWiredThrough:
    def test_build_request_includes_temperature_when_env_set(self, monkeypatch):
        from maverick.providers.anthropic_provider import AnthropicClient
        # Avoid touching the real anthropic client constructor.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        monkeypatch.setenv("MAVERICK_TEMPERATURE", "0.85")
        client = AnthropicClient()
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=128,
            thinking_budget=None,
            model="claude-sonnet-4-6",
        )
        assert kwargs.get("temperature") == 0.85

    def test_build_request_no_temperature_when_unset(self, monkeypatch):
        from maverick.providers.anthropic_provider import AnthropicClient
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        monkeypatch.delenv("MAVERICK_TEMPERATURE", raising=False)
        client = AnthropicClient()
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=128,
            thinking_budget=None,
            model="claude-sonnet-4-6",
        )
        assert "temperature" not in kwargs

    def test_build_request_no_temperature_when_thinking_enabled(self, monkeypatch):
        # Thinking models reject explicit temperature; gate must hold.
        from maverick.providers.anthropic_provider import AnthropicClient
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        monkeypatch.setenv("MAVERICK_TEMPERATURE", "0.9")
        client = AnthropicClient()
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=128,
            thinking_budget=4000,
            model="claude-opus-4-7",
        )
        assert "temperature" not in kwargs


# ---- B1: str_replace_editor tool ----

class TestStrReplaceEditor:
    def _make_sandbox(self, tmp_path):
        class _Sandbox:
            workdir = tmp_path
        return _Sandbox()

    def test_view_file_returns_numbered_lines(self, tmp_path):
        from maverick.tools.str_edit import str_replace_editor
        (tmp_path / "foo.py").write_text("a\nb\nc\n")
        tool = str_replace_editor(self._make_sandbox(tmp_path))
        out = tool.fn({"command": "view", "path": "foo.py"})
        assert "1: a" in out
        assert "2: b" in out
        assert "3: c" in out

    def test_str_replace_exact_match_succeeds(self, tmp_path):
        from maverick.tools.str_edit import str_replace_editor
        (tmp_path / "foo.py").write_text("hello world\n")
        tool = str_replace_editor(self._make_sandbox(tmp_path))
        out = tool.fn({
            "command": "str_replace", "path": "foo.py",
            "old_str": "hello world", "new_str": "hello universe",
        })
        assert "edited" in out
        assert (tmp_path / "foo.py").read_text() == "hello universe\n"

    def test_str_replace_no_match_refuses(self, tmp_path):
        from maverick.tools.str_edit import str_replace_editor
        (tmp_path / "foo.py").write_text("hello world\n")
        tool = str_replace_editor(self._make_sandbox(tmp_path))
        out = tool.fn({
            "command": "str_replace", "path": "foo.py",
            "old_str": "goodbye", "new_str": "hi",
        })
        assert "ERROR" in out
        assert "not found" in out.lower()
        # File must be unchanged.
        assert (tmp_path / "foo.py").read_text() == "hello world\n"

    def test_str_replace_ambiguous_refuses(self, tmp_path):
        from maverick.tools.str_edit import str_replace_editor
        (tmp_path / "foo.py").write_text("x = 1\nx = 1\n")
        tool = str_replace_editor(self._make_sandbox(tmp_path))
        out = tool.fn({
            "command": "str_replace", "path": "foo.py",
            "old_str": "x = 1", "new_str": "x = 2",
        })
        assert "ambiguous" in out.lower()
        assert "2 times" in out
        # File must be unchanged.
        assert (tmp_path / "foo.py").read_text() == "x = 1\nx = 1\n"

    def test_str_replace_whitespace_drift_hint(self, tmp_path):
        from maverick.tools.str_edit import str_replace_editor
        # File has trailing whitespace on the line; user supplies the
        # trimmed version (does NOT match byte-for-byte, but DOES match
        # after rstrip-per-line normalisation).
        (tmp_path / "foo.py").write_text("def f():\n    return 1   \n")
        tool = str_replace_editor(self._make_sandbox(tmp_path))
        out = tool.fn({
            "command": "str_replace", "path": "foo.py",
            "old_str": "def f():\n    return 1\n",
            "new_str": "def f():\n    return 2\n",
        })
        assert "ERROR" in out
        assert "whitespace" in out.lower()

    def test_create_new_file(self, tmp_path):
        from maverick.tools.str_edit import str_replace_editor
        tool = str_replace_editor(self._make_sandbox(tmp_path))
        out = tool.fn({
            "command": "create", "path": "new.py",
            "file_text": "x = 42\n",
        })
        assert "created" in out
        assert (tmp_path / "new.py").read_text() == "x = 42\n"

    def test_create_refuses_overwrite(self, tmp_path):
        from maverick.tools.str_edit import str_replace_editor
        (tmp_path / "existing.py").write_text("old\n")
        tool = str_replace_editor(self._make_sandbox(tmp_path))
        out = tool.fn({
            "command": "create", "path": "existing.py",
            "file_text": "new\n",
        })
        assert "already exists" in out
        assert (tmp_path / "existing.py").read_text() == "old\n"


# ---- S1: read_file refuses tests in benchmark opaque mode ----

class TestReadFileOpaqueGuard:
    def _make_sandbox(self, tmp_path):
        class _Sandbox:
            workdir = tmp_path
        return _Sandbox()

    def test_read_test_file_blocked_when_opaque(self, tmp_path, monkeypatch):
        from maverick.tools.fs import read_file
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_foo.py").write_text("assert x == 42")
        monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "1")
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        tool = read_file(self._make_sandbox(tmp_path))
        out = tool.fn({"path": "tests/test_foo.py"})
        assert "blocked" in out.lower()
        assert "x == 42" not in out

    def test_read_production_file_still_works(self, tmp_path, monkeypatch):
        from maverick.tools.fs import read_file
        (tmp_path / "src.py").write_text("def f(): return 42")
        monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "1")
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        tool = read_file(self._make_sandbox(tmp_path))
        out = tool.fn({"path": "src.py"})
        assert "return 42" in out

    def test_opaque_off_allows_test_reads(self, tmp_path, monkeypatch):
        from maverick.tools.fs import read_file
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_foo.py").write_text("assert x == 42")
        monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "0")
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        tool = read_file(self._make_sandbox(tmp_path))
        out = tool.fn({"path": "tests/test_foo.py"})
        assert "x == 42" in out


# ---- S2: shell refuses git log -p / git show in opaque mode ----

class TestShellOpaqueGuard:
    def _make_sandbox(self, tmp_path):
        class _Sandbox:
            workdir = tmp_path
            timeout = 30.0

            def exec(self, cmd):
                from maverick.sandbox.local import ExecResult
                return ExecResult(stdout="ran: " + cmd, stderr="", exit_code=0)
        return _Sandbox()

    def test_git_log_patch_blocked(self, tmp_path, monkeypatch):
        from maverick.tools.shell import shell
        monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "1")
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        tool = shell(self._make_sandbox(tmp_path))
        out = tool.fn({"cmd": "git log -p HEAD~1"})
        assert "blocked" in out.lower()
        assert "ran:" not in out

    def test_git_show_blocked(self, tmp_path, monkeypatch):
        from maverick.tools.shell import shell
        monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "1")
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        tool = shell(self._make_sandbox(tmp_path))
        out = tool.fn({"cmd": "git show HEAD~1"})
        assert "blocked" in out.lower()

    def test_normal_git_diff_allowed(self, tmp_path, monkeypatch):
        from maverick.tools.shell import shell
        monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "1")
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        tool = shell(self._make_sandbox(tmp_path))
        # plain `git diff` (HEAD vs worktree) is the normal path -- allowed.
        out = tool.fn({"cmd": "git diff"})
        assert "ran:" in out
        assert "blocked" not in out.lower()

    def test_pytest_allowed(self, tmp_path, monkeypatch):
        from maverick.tools.shell import shell
        monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "1")
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        tool = shell(self._make_sandbox(tmp_path))
        out = tool.fn({"cmd": "pytest tests/test_foo.py"})
        assert "ran:" in out

    def test_opaque_off_allows_git_log_patch(self, tmp_path, monkeypatch):
        from maverick.tools.shell import shell
        monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "0")
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        tool = shell(self._make_sandbox(tmp_path))
        out = tool.fn({"cmd": "git log -p"})
        assert "ran:" in out


# ---- D7: load_instances tolerates malformed JSON lines ----

class TestLoadInstancesTolerant:
    def test_malformed_json_line_is_skipped_not_raises(self, tmp_path, capsys):
        import importlib.util
        import sys
        from pathlib import Path
        # Resolve relative to this test file so the path is correct in any
        # checkout location (local dev, CI runner, etc.).
        # tests/test_wave10.py → packages/maverick-core/tests → repo root → benchmarks/swe_bench.py
        repo_root = Path(__file__).resolve().parents[3]
        p = repo_root / "benchmarks" / "swe_bench.py"
        assert p.exists(), f"benchmarks/swe_bench.py not found at {p}"
        spec = importlib.util.spec_from_file_location("benchmarks_swe_bench", p)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["benchmarks_swe_bench"] = mod
        spec.loader.exec_module(mod)

        manifest = tmp_path / "m.jsonl"
        manifest.write_text(
            '{"instance_id": "good", "brief": "fix"}\n'
            '{this is broken\n'  # malformed
            '{"instance_id": "good2", "brief": "fix2"}\n'
        )
        out = mod.load_instances(manifest)
        assert [d["instance_id"] for d in out] == ["good", "good2"]
        err = capsys.readouterr().err
        assert "malformed JSON" in err or "JSONDecodeError" in err or "warning:" in err


# ---- C1: predicted_patch in CSV uses extracted diff, not prose ----

class TestPredictedPatchExtraction:
    def test_extract_unified_diff_used_in_row_construction(self):
        # Smoke: the import works and the function name matches.
        from maverick.coding_mode import extract_unified_diff
        prose = (
            "DONE.\n\nHere's the fix:\n\n```diff\n"
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
            "```\n\n[budget: $1.20]"
        )
        diff = extract_unified_diff(prose)
        assert diff is not None
        assert diff.startswith("--- a/foo.py")
        assert "+new" in diff


# ---- B3: coding-mode template enforces 3-phase plan ----

class TestCodingModeTemplate:
    def test_template_mentions_three_phases(self):
        from maverick.coding_mode import CODER_CODING_MODE_TEMPLATE
        # Wave 10 (B3): LOCALIZE → EDIT → VERIFY is the canonical
        # OpenHands / Aider playbook. Pinning the template guarantees
        # the orchestrator instructs the model in this order.
        assert "LOCALIZE" in CODER_CODING_MODE_TEMPLATE
        assert "EDIT" in CODER_CODING_MODE_TEMPLATE
        assert "VERIFY" in CODER_CODING_MODE_TEMPLATE

    def test_template_recommends_str_replace_editor(self):
        from maverick.coding_mode import CODER_CODING_MODE_TEMPLATE
        assert "str_replace_editor" in CODER_CODING_MODE_TEMPLATE
