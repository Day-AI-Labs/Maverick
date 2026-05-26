"""Wave 12: security hardening.

Covers council findings F9b-F9f:
  - F9b: str_replace_editor.view bypassed opaque-mode test-file block
  - F9c: subprocess inherited MAVERICK_GOLD_PATCH from env
  - F9d: .git/ reads not blocked (refs + objects leak the gold)
  - F9f: MAVERICK_GOLD_PATCH popped on first read (defense in depth)
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture
def opaque_mode(monkeypatch):
    monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "1")
    monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
    from maverick.coding_mode import reset_gold_patch_cache
    reset_gold_patch_cache()
    yield
    reset_gold_patch_cache()


class TestGoldPatchPopped:
    def test_first_read_pops_env_var(self, monkeypatch):
        from maverick.coding_mode import (
            get_gold_patch,
            reset_gold_patch_cache,
        )
        reset_gold_patch_cache()
        monkeypatch.setenv("MAVERICK_GOLD_PATCH", "diff --git a/x b/x\n+gold\n")
        assert "MAVERICK_GOLD_PATCH" in os.environ
        val = get_gold_patch()
        assert "gold" in val
        # The env var must be popped — agent's shell cannot see it.
        assert "MAVERICK_GOLD_PATCH" not in os.environ
        reset_gold_patch_cache()

    def test_subsequent_reads_return_cached(self, monkeypatch):
        from maverick.coding_mode import (
            get_gold_patch,
            reset_gold_patch_cache,
        )
        reset_gold_patch_cache()
        monkeypatch.setenv("MAVERICK_GOLD_PATCH", "cached value\n")
        first = get_gold_patch()
        second = get_gold_patch()
        third = get_gold_patch()
        assert first == second == third == "cached value\n"
        reset_gold_patch_cache()

    def test_new_instance_overwrites_cache(self, monkeypatch):
        from maverick.coding_mode import (
            get_gold_patch,
            reset_gold_patch_cache,
        )
        reset_gold_patch_cache()
        monkeypatch.setenv("MAVERICK_GOLD_PATCH", "instance_a")
        assert get_gold_patch() == "instance_a"
        # Harness moves to next instance and sets a different gold.
        monkeypatch.setenv("MAVERICK_GOLD_PATCH", "instance_b")
        assert get_gold_patch() == "instance_b"
        reset_gold_patch_cache()

    def test_no_env_returns_empty(self, monkeypatch):
        from maverick.coding_mode import (
            get_gold_patch,
            reset_gold_patch_cache,
        )
        reset_gold_patch_cache()
        monkeypatch.delenv("MAVERICK_GOLD_PATCH", raising=False)
        assert get_gold_patch() == ""


class TestDotGitBlocked:
    def test_read_file_blocks_dotgit(self, tmp_path, opaque_mode):
        from maverick.tools.fs import read_file
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

        class _Sandbox:
            workdir = tmp_path

        tool = read_file(_Sandbox())
        out = tool.fn({"path": ".git/HEAD"})
        assert "ERROR" in out
        assert "blocked" in out.lower()

    def test_read_file_blocks_nested_dotgit(self, tmp_path, opaque_mode):
        from maverick.tools.fs import read_file
        (tmp_path / "sub" / ".git").mkdir(parents=True)
        (tmp_path / "sub" / ".git" / "config").write_text("[core]\n")

        class _Sandbox:
            workdir = tmp_path

        tool = read_file(_Sandbox())
        out = tool.fn({"path": "sub/.git/config"})
        assert "ERROR" in out

    def test_read_file_allows_dotgit_in_non_opaque(self, tmp_path, monkeypatch):
        from maverick.tools.fs import read_file
        monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "0")
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

        class _Sandbox:
            workdir = tmp_path

        tool = read_file(_Sandbox())
        out = tool.fn({"path": ".git/HEAD"})
        # No opaque-mode block; gets through to file read.
        assert "ref: refs/heads/main" in out


class TestStrReplaceEditorOpacity:
    """F9b: str_replace_editor.view was the opacity backdoor — same
    file gating as read_file must apply."""

    def test_view_blocks_test_file_in_opaque(self, tmp_path, opaque_mode):
        from maverick.tools.str_edit import str_replace_editor
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_foo.py").write_text(
            "assert expected_value == 42\n"
        )

        class _Sandbox:
            workdir = tmp_path

        tool = str_replace_editor(_Sandbox())
        out = tool.fn({"command": "view", "path": "tests/test_foo.py"})
        assert "ERROR" in out
        assert "expected_value" not in out, (
            "test content leaked through view despite opaque mode"
        )

    def test_view_blocks_dotgit(self, tmp_path, opaque_mode):
        from maverick.tools.str_edit import str_replace_editor
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

        class _Sandbox:
            workdir = tmp_path

        tool = str_replace_editor(_Sandbox())
        out = tool.fn({"command": "view", "path": ".git/HEAD"})
        assert "ERROR" in out
        assert "ref:" not in out

    def test_view_production_file_allowed(self, tmp_path, opaque_mode):
        from maverick.tools.str_edit import str_replace_editor
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("def f():\n    return 1\n")

        class _Sandbox:
            workdir = tmp_path

        tool = str_replace_editor(_Sandbox())
        out = tool.fn({"command": "view", "path": "src/app.py"})
        assert "ERROR" not in out
        assert "def f" in out


class TestShellGitInternalsBlocked:
    """F9d: shell-level git plumbing + raw .git filesystem access."""

    def _shell(self, tmp_path):
        from maverick.tools.shell import shell

        class _Sandbox:
            workdir = tmp_path
            timeout = 5.0

            def exec(self, cmd, timeout=None):
                from maverick.sandbox.local import ExecResult
                return ExecResult(stdout="ok", stderr="", exit_code=0)

        return shell(_Sandbox())

    def test_git_cat_file_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "git cat-file -p HEAD"})
        assert "blocked" in out.lower()

    def test_git_for_each_ref_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "git for-each-ref"})
        assert "blocked" in out.lower()

    def test_cat_dotgit_refs_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "cat .git/refs/heads/main"})
        assert "blocked" in out.lower()

    def test_find_dotgit_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "find .git -type f"})
        assert "blocked" in out.lower()

    def test_legitimate_git_status_allowed(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "git status"})
        assert "blocked" not in out.lower()
        assert "ok" in out


class TestShellPopsGoldPatch:
    """F9c: subprocess must not inherit MAVERICK_GOLD_PATCH. The shell
    tool defensively pops the env var before forwarding to sandbox."""

    def test_shell_pops_gold_patch_in_opaque(self, tmp_path, monkeypatch):
        from maverick.coding_mode import reset_gold_patch_cache
        from maverick.tools.shell import shell
        reset_gold_patch_cache()
        monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "1")
        monkeypatch.setenv("MAVERICK_GOLD_PATCH", "the gold")

        captured_env = {}

        class _Sandbox:
            workdir = tmp_path
            timeout = 5.0

            def exec(self, cmd, timeout=None):
                from maverick.sandbox.local import ExecResult
                captured_env["MAVERICK_GOLD_PATCH"] = os.environ.get(
                    "MAVERICK_GOLD_PATCH"
                )
                return ExecResult(stdout="", stderr="", exit_code=0)

        tool = shell(_Sandbox())
        tool.fn({"cmd": "echo hello"})
        assert captured_env.get("MAVERICK_GOLD_PATCH") is None, (
            "subprocess saw MAVERICK_GOLD_PATCH — gold answer leaked "
            "via env to the agent's sandboxed shell"
        )
        reset_gold_patch_cache()
