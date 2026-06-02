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


class TestSymlinkBypass:
    """Wave 12 hardening: symlink to .git or tests/ must still be
    blocked by the resolved-path check."""

    @pytest.mark.skipif(
        os.name == "nt",
        reason="creating a symlink requires admin/Developer Mode on Windows (WinError 1314)",
    )
    def test_symlink_to_dotgit_blocked_in_read_file(self, tmp_path, opaque_mode):
        import os as _os

        from maverick.tools.fs import read_file
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        # Create symlink: safe_dir -> .git
        _os.symlink(".git", tmp_path / "safe_dir")

        class _Sandbox:
            workdir = tmp_path

        tool = read_file(_Sandbox())
        out = tool.fn({"path": "safe_dir/HEAD"})
        assert "ERROR" in out, (
            "symlink to .git/HEAD must be blocked on resolved path"
        )
        assert "ref:" not in out

    @pytest.mark.skipif(
        os.name == "nt",
        reason="creating a symlink requires admin/Developer Mode on Windows (WinError 1314)",
    )
    def test_symlink_to_tests_blocked_in_view(self, tmp_path, opaque_mode):
        import os as _os

        from maverick.tools.str_edit import str_replace_editor
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_foo.py").write_text(
            "assert expected_value == 42\n"
        )
        _os.symlink("tests", tmp_path / "looks_like_src")

        class _Sandbox:
            workdir = tmp_path

        tool = str_replace_editor(_Sandbox())
        out = tool.fn({"command": "view", "path": "looks_like_src/test_foo.py"})
        assert "ERROR" in out
        assert "expected_value" not in out


class TestTestsDirAllFiles:
    """Wave 12 hardening: ANY file under tests/ is now blocked, not
    just files matching the test_*.py heuristic."""

    def test_conftest_under_tests_blocked(self, tmp_path, opaque_mode):
        from maverick.tools.fs import read_file
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "conftest.py").write_text("# expected_value = 42")

        class _Sandbox:
            workdir = tmp_path

        tool = read_file(_Sandbox())
        out = tool.fn({"path": "tests/conftest.py"})
        assert "ERROR" in out
        assert "expected_value" not in out

    def test_init_under_tests_blocked(self, tmp_path, opaque_mode):
        from maverick.tools.fs import read_file
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "__init__.py").write_text("EXPECTED = 'gold'")

        class _Sandbox:
            workdir = tmp_path

        tool = read_file(_Sandbox())
        out = tool.fn({"path": "tests/__init__.py"})
        assert "ERROR" in out
        assert "gold" not in out


class TestShellGitFlagsBypass:
    """Wave 12 hardening (agent 2 #3): git plumbing wasn't blocked
    when preceded by `-P`, `--git-dir=...`, `-c k=v`, etc."""

    def _shell(self, tmp_path):
        from maverick.tools.shell import shell

        class _Sandbox:
            workdir = tmp_path
            timeout = 5.0

            def exec(self, cmd, timeout=None):
                from maverick.sandbox.local import ExecResult
                return ExecResult(stdout="ok", stderr="", exit_code=0)

        return shell(_Sandbox())

    def test_git_dash_p_log_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "git -P log -p HEAD"})
        assert "blocked" in out.lower()

    def test_git_dash_c_log_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "git -c color.ui=never log -p HEAD"})
        assert "blocked" in out.lower()

    def test_git_dash_dash_git_dir_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "git --git-dir=/workdir/.git rev-list HEAD"})
        assert "blocked" in out.lower()

    def test_git_rev_list_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "git rev-list HEAD"})
        assert "blocked" in out.lower()

    def test_git_show_ref_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "git show-ref"})
        assert "blocked" in out.lower()

    def test_git_ls_files_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "git ls-files --stage"})
        assert "blocked" in out.lower()


class TestShellAnyUtilityReadsDotGit:
    """Wave 12 hardening (agent 2 #2): block .git/<sensitive> reads
    regardless of consuming utility — python, awk, xxd, grep, sed,
    cp, mv, tar all bypass the prior cat-blocker."""

    def _shell(self, tmp_path):
        from maverick.tools.shell import shell

        class _Sandbox:
            workdir = tmp_path
            timeout = 5.0

            def exec(self, cmd, timeout=None):
                from maverick.sandbox.local import ExecResult
                return ExecResult(stdout="ok", stderr="", exit_code=0)

        return shell(_Sandbox())

    def test_python_read_dotgit_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({
            "cmd": "python -c \"print(open('.git/HEAD').read())\"",
        })
        assert "blocked" in out.lower()

    def test_awk_read_dotgit_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "awk 1 .git/HEAD"})
        assert "blocked" in out.lower()

    def test_grep_dotgit_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "grep -r HEAD .git/refs"})
        assert "blocked" in out.lower()

    def test_cp_dotgit_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "cp .git/HEAD /tmp/leak"})
        assert "blocked" in out.lower()

    def test_sed_dotgit_blocked(self, tmp_path, opaque_mode):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "sed n .git/refs/heads/main"})
        assert "blocked" in out.lower()


class TestGoldPatchEmptyEnvSentinel:
    """Wave 12 hardening (agent 2 #5): empty-string MAVERICK_GOLD_PATCH
    should pop+cache, NOT be treated as 'not yet read'."""

    def test_empty_env_is_popped_and_cached(self, monkeypatch):
        import os as _os

        from maverick.coding_mode import (
            get_gold_patch,
            reset_gold_patch_cache,
        )
        reset_gold_patch_cache()
        monkeypatch.setenv("MAVERICK_GOLD_PATCH", "")
        out = get_gold_patch()
        assert out == ""
        # Env var must still be popped.
        assert "MAVERICK_GOLD_PATCH" not in _os.environ
        # The cache is now "" (empty), but explicitly POPPED.
        from maverick import coding_mode
        assert coding_mode._GOLD_PATCH_POPPED is True
        reset_gold_patch_cache()


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


class TestOpaqueGoldLeakGaps474:
    """#474: close opaque-mode gold-leak blocklist gaps.

    Three gaps: single-ref `git diff <ref>` (no `..`), patch-emitting
    porcelain (format-patch --stdout / whatchanged / archive / bundle
    create / log --format=%H), and `.git` laundering to a non-`.git`
    name (cp/ln/tar/rsync .git). All blocked ONLY in opaque mode;
    normal-mode `git diff`/`git log` must keep working.
    """

    def _shell(self, tmp_path):
        from maverick.tools.shell import shell

        class _Sandbox:
            workdir = tmp_path
            timeout = 5.0

            def exec(self, cmd, timeout=None):
                from maverick.sandbox.local import ExecResult
                return ExecResult(stdout="ok", stderr="", exit_code=0)

        return shell(_Sandbox())

    # --- Task 1: single-ref `git diff <ref>` ---

    @pytest.mark.parametrize("cmd", [
        "git diff main",
        "git diff origin/main",
        "git diff HEAD~1",
        "git diff abc1234",
        "git -P diff main",
    ])
    def test_git_diff_single_ref_blocked(self, tmp_path, opaque_mode, cmd):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": cmd})
        assert "blocked" in out.lower(), cmd

    @pytest.mark.parametrize("cmd", [
        "git diff",
        "git diff --staged",
        "git diff --cached -- file.py",
        "git diff HEAD",
        "git diff HEAD --",
        "git diff -- path/to/file",
    ])
    def test_legit_git_diff_allowed_in_opaque(self, tmp_path, opaque_mode, cmd):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": cmd})
        assert "blocked" not in out.lower(), cmd
        assert "ok" in out

    # --- Task 2: patch-emitting porcelain ---

    @pytest.mark.parametrize("cmd", [
        "git format-patch HEAD~1 --stdout",
        "git whatchanged -p",
        "git archive HEAD",
        "git bundle create out.bundle HEAD",
        "git log --format=%H",
        "git log --pretty=%H",
    ])
    def test_patch_porcelain_blocked(self, tmp_path, opaque_mode, cmd):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": cmd})
        assert "blocked" in out.lower(), cmd

    # --- Task 3: .git laundering to a non-.git name ---

    @pytest.mark.parametrize("cmd", [
        "cp -r .git /tmp/g && cat /tmp/g/HEAD",
        "ln -s .git gd",
        "tar cf - .git",
        "rsync -a .git /tmp/x",
    ])
    def test_dotgit_laundering_blocked(self, tmp_path, opaque_mode, cmd):
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": cmd})
        assert "blocked" in out.lower(), cmd

    def test_gitignore_not_overblocked(self, tmp_path, opaque_mode):
        # `.gitignore` must not trip the `.git` laundering rule.
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": "cat .gitignore"})
        assert "blocked" not in out.lower()
        assert "ok" in out

    # --- Normal mode: none of the new blocks apply ---

    @pytest.mark.parametrize("cmd", [
        "git diff main",
        "git diff HEAD~1",
        "git format-patch HEAD~1 --stdout",
        "git whatchanged -p",
        "git archive HEAD",
        "git bundle create out.bundle HEAD",
        "git log --format=%H",
        "cp -r .git /tmp/g",
        "ln -s .git gd",
        "tar cf - .git",
    ])
    def test_all_allowed_in_normal_mode(self, tmp_path, monkeypatch, cmd):
        monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "0")
        monkeypatch.delenv("MAVERICK_CODING_MODE", raising=False)
        tool = self._shell(tmp_path)
        out = tool.fn({"cmd": cmd})
        assert "blocked" not in out.lower(), cmd
        assert "ok" in out
