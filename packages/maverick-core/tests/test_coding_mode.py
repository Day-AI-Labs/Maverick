"""Wave 8: coding mode, patch validation, test-driven verifier, repo_map."""
from __future__ import annotations

import subprocess
from pathlib import Path


from maverick.coding_mode import (
    Candidate,
    extract_unified_diff,
    from_env,
    select_best_candidate,
    validate_patch,
)


class TestExtractUnifiedDiff:
    def test_plain_diff(self):
        text = (
            "--- a/foo.py\n+++ b/foo.py\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        )
        out = extract_unified_diff(text)
        assert out is not None
        assert "--- a/foo.py" in out
        assert "+new" in out

    def test_strips_final_prefix(self):
        text = (
            "FINAL:\n"
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
        )
        out = extract_unified_diff(text)
        assert "FINAL:" not in out

    def test_extracts_from_markdown_fence(self):
        text = (
            "Here's the patch:\n"
            "```diff\n"
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
            "```\n"
        )
        out = extract_unified_diff(text)
        assert "--- a/foo.py" in out

    def test_multi_file_diff_kept_together(self):
        text = (
            "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-1\n+2\n"
            "--- a/y.py\n+++ b/y.py\n@@ -1 +1 @@\n-3\n+4\n"
        )
        out = extract_unified_diff(text)
        assert "x.py" in out
        assert "y.py" in out

    def test_no_diff_returns_none(self):
        assert extract_unified_diff("just prose, nothing to patch") is None

    def test_empty_returns_none(self):
        assert extract_unified_diff("") is None
        assert extract_unified_diff(None) is None


class TestValidatePatch:
    def _init_git_repo(self, tmp_path: Path) -> Path:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        # Test scaffold only — disable sign for the throwaway fixture
        # so tests don't depend on the test env's git signing config.
        for key, val in [
            ("user.email", "t@t"),
            ("user.name", "t"),
            ("commit.gpgsign", "false"),
        ]:
            subprocess.run(
                ["git", "-C", str(tmp_path), "config", key, val], check=True,
            )
        (tmp_path / "foo.py").write_text("old line\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True,
        )
        return tmp_path

    def test_valid_patch_passes(self, tmp_path):
        repo = self._init_git_repo(tmp_path)
        patch = (
            "--- a/foo.py\n+++ b/foo.py\n"
            "@@ -1 +1 @@\n-old line\n+new line\n"
        )
        v = validate_patch(patch, repo)
        assert v.valid is True

    def test_unapplyable_patch_fails(self, tmp_path):
        repo = self._init_git_repo(tmp_path)
        # Patch references content that doesn't exist.
        patch = (
            "--- a/foo.py\n+++ b/foo.py\n"
            "@@ -1 +1 @@\n-DIFFERENT LINE\n+new line\n"
        )
        v = validate_patch(patch, repo)
        assert v.valid is False
        assert "rejected" in v.reason

    def test_empty_patch_fails(self, tmp_path):
        v = validate_patch("", tmp_path)
        assert v.valid is False

    def test_missing_headers_fails(self, tmp_path):
        v = validate_patch("just some text", tmp_path)
        assert v.valid is False
        assert "headers" in v.reason

    def test_non_git_dir_fails(self, tmp_path):
        v = validate_patch("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n", tmp_path)
        assert v.valid is False
        assert "not a git" in v.reason


class TestSelectBestCandidate:
    def test_highest_score_wins(self):
        a = Candidate(0, "patch a", score=0.5, apply_check_passed=True)
        b = Candidate(1, "patch b", score=0.9, apply_check_passed=True)
        c = Candidate(2, "patch c", score=0.7, apply_check_passed=True)
        assert select_best_candidate([a, b, c]) is b

    def test_smaller_patch_wins_ties(self):
        a = Candidate(0, "longer patch text", score=0.8, apply_check_passed=True)
        b = Candidate(1, "short", score=0.8, apply_check_passed=True)
        assert select_best_candidate([a, b]) is b

    def test_apply_check_required(self):
        bad = Candidate(0, "x", score=0.95, apply_check_passed=False)
        ok = Candidate(1, "y", score=0.5, apply_check_passed=True)
        assert select_best_candidate([bad, ok]) is ok

    def test_empty_returns_none(self):
        assert select_best_candidate([]) is None

    def test_all_unusable_picks_anything_with_content(self):
        a = Candidate(0, "", score=0.0, apply_check_passed=False)
        b = Candidate(1, "some patch", score=0.0, apply_check_passed=False)
        assert select_best_candidate([a, b]) is b


class TestCodingModeFromEnv:
    def test_default_disabled(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_CODING_MODE", raising=False)
        cfg = from_env()
        assert cfg.enabled is False
        assert cfg.best_of_n == 1
        assert cfg.fail_to_pass == []

    def test_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        cfg = from_env()
        assert cfg.enabled is True

    def test_best_of_n(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_BEST_OF_N", "4")
        assert from_env().best_of_n == 4

    def test_fail_to_pass_parsed(self, monkeypatch):
        monkeypatch.setenv(
            "MAVERICK_FAIL_TO_PASS",
            "tests/test_a.py::test_x||tests/test_a.py::test_y",
        )
        cfg = from_env()
        assert len(cfg.fail_to_pass) == 2
        assert "tests/test_a.py::test_x" in cfg.fail_to_pass

    def test_bad_best_of_n_falls_back(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_BEST_OF_N", "high")
        assert from_env().best_of_n == 1


class TestTestRunResult:
    def test_all_pass_property(self):
        from maverick.coding_mode import TestRunResult
        r = TestRunResult(
            fail_to_pass_passing=3, fail_to_pass_total=3,
            pass_to_pass_passing=10, pass_to_pass_total=10,
        )
        assert r.all_pass is True
        assert r.score == 1.0

    def test_partial_pass(self):
        from maverick.coding_mode import TestRunResult
        r = TestRunResult(
            fail_to_pass_passing=2, fail_to_pass_total=3,
            pass_to_pass_passing=10, pass_to_pass_total=10,
        )
        assert r.all_pass is False
        assert 0.9 < r.score < 1.0

    def test_error_zeros_score(self):
        from maverick.coding_mode import TestRunResult
        r = TestRunResult(error="sandbox crashed")
        assert r.all_pass is False
        assert r.score == 0.0

    def test_summary_renders(self):
        from maverick.coding_mode import TestRunResult
        r = TestRunResult(
            fail_to_pass_passing=2, fail_to_pass_total=3,
            pass_to_pass_passing=10, pass_to_pass_total=10,
        )
        s = r.summary()
        assert "2/3" in s
        assert "10/10" in s


class TestRepoMapTool:
    def test_emits_top_level_listing(self, tmp_path):
        from maverick.tools.repo_map import repo_map
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hi')")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test(): pass")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        class _Sandbox:
            workdir = tmp_path

        tool = repo_map(_Sandbox())
        out = tool.fn({})
        assert "src/" in out
        assert "tests/" in out
        assert "pyproject.toml" in out
        # Language detection picks up the marker.
        assert "Python (pyproject)" in out

    def test_ignores_dotgit_and_venv(self, tmp_path):
        from maverick.tools.repo_map import repo_map
        (tmp_path / ".git").mkdir()
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "x.py").write_text("")

        class _Sandbox:
            workdir = tmp_path

        out = repo_map(_Sandbox()).fn({})
        assert ".git" not in out
        assert "node_modules" not in out
        assert "src/" in out

    def test_missing_workdir_error(self, tmp_path):
        from maverick.tools.repo_map import repo_map

        class _Sandbox:
            workdir = tmp_path / "nonexistent"

        out = repo_map(_Sandbox()).fn({})
        assert "ERROR" in out


class TestRepoMapInRegistry:
    def test_repo_map_registered(self, tmp_path):
        """The base registry now ships repo_map as a default tool."""
        from maverick.sandbox import LocalBackend
        from maverick.tools import base_registry
        from maverick.world_model import WorldModel

        wm = WorldModel(path=tmp_path / "w.db")
        reg = base_registry(wm, LocalBackend(workdir=tmp_path))
        names = {t.name for t in reg.all()}
        assert "repo_map" in names
