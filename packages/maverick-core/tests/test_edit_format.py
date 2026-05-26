"""Tests for the SEARCH/REPLACE edit format module (Wave 11)."""
from __future__ import annotations

import subprocess
from pathlib import Path


def _make_git_repo(tmp_path: Path) -> Path:
    """Init a tiny git repo with a single committed file for tests."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "commit.gpgsign", "false"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "seed.py").write_text(
        "def add(a, b):\n    return a + b\n"
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "seed.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "seed"],
        check=True,
    )
    return tmp_path


# ---- parse_blocks ----

class TestParseBlocks:
    def test_single_block(self):
        from maverick.edit_format import parse_blocks
        text = (
            "Here's the fix:\n"
            "foo.py\n"
            "<<<<<<< SEARCH\n"
            "old\n"
            "=======\n"
            "new\n"
            ">>>>>>> REPLACE\n"
        )
        blocks = parse_blocks(text)
        assert len(blocks) == 1
        assert blocks[0].path == "foo.py"
        assert blocks[0].search == "old\n"
        assert blocks[0].replace == "new\n"

    def test_multiple_blocks_different_files(self):
        from maverick.edit_format import parse_blocks
        text = (
            "a.py\n<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE\n"
            "b.py\n<<<<<<< SEARCH\nm\n=======\nn\n>>>>>>> REPLACE\n"
        )
        blocks = parse_blocks(text)
        assert len(blocks) == 2
        assert blocks[0].path == "a.py"
        assert blocks[1].path == "b.py"

    def test_empty_search_means_new_file(self):
        from maverick.edit_format import parse_blocks
        text = (
            "new.py\n"
            "<<<<<<< SEARCH\n"
            "=======\n"
            "x = 1\n"
            ">>>>>>> REPLACE\n"
        )
        blocks = parse_blocks(text)
        assert len(blocks) == 1
        assert blocks[0].search == ""
        assert blocks[0].replace == "x = 1\n"

    def test_handles_crlf_input(self):
        from maverick.edit_format import parse_blocks
        text = (
            "foo.py\r\n<<<<<<< SEARCH\r\nold\r\n=======\r\nnew\r\n>>>>>>> REPLACE\r\n"
        )
        blocks = parse_blocks(text)
        assert len(blocks) == 1
        assert blocks[0].path == "foo.py"

    def test_strips_code_fences_before_path(self):
        from maverick.edit_format import parse_blocks
        text = (
            "```python\nfoo.py\n```\n"
            "foo.py\n<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE\n"
        )
        blocks = parse_blocks(text)
        assert len(blocks) == 1
        assert blocks[0].path == "foo.py"

    def test_no_blocks_returns_empty(self):
        from maverick.edit_format import parse_blocks
        assert parse_blocks("just prose") == []
        assert parse_blocks("") == []

    def test_accepts_extra_marker_chars(self):
        from maverick.edit_format import parse_blocks
        text = "foo.py\n<<<<<<<<< SEARCH\nx\n========\ny\n>>>>>>>>> REPLACE\n"
        blocks = parse_blocks(text)
        assert len(blocks) == 1


# ---- apply_blocks ----

class TestApplyBlocks:
    def test_exact_match_applies(self, tmp_path):
        from maverick.edit_format import SearchReplaceBlock, apply_blocks
        repo = _make_git_repo(tmp_path)
        blk = SearchReplaceBlock(
            path="seed.py",
            search="def add(a, b):\n    return a + b\n",
            replace="def add(a, b):\n    return a + b + 0\n",
        )
        summary = apply_blocks([blk], repo)
        assert summary.ok
        assert summary.results[0].match_kind == "exact"
        assert (repo / "seed.py").read_text() == "def add(a, b):\n    return a + b + 0\n"

    def test_trailing_whitespace_drift_recovered(self, tmp_path):
        from maverick.edit_format import SearchReplaceBlock, apply_blocks
        repo = _make_git_repo(tmp_path)
        # File has trailing whitespace; model supplies trimmed.
        (repo / "seed.py").write_text("def add(a, b):   \n    return a + b   \n")
        subprocess.run(["git", "-C", str(repo), "add", "seed.py"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "whitespace"],
            check=True,
        )
        blk = SearchReplaceBlock(
            path="seed.py",
            search="def add(a, b):\n    return a + b\n",
            replace="def add(a, b):\n    return a + b + 0\n",
        )
        summary = apply_blocks([blk], repo)
        assert summary.ok
        assert summary.results[0].match_kind == "rstrip"

    def test_no_match_reports_near_miss(self, tmp_path):
        from maverick.edit_format import SearchReplaceBlock, apply_blocks
        repo = _make_git_repo(tmp_path)
        blk = SearchReplaceBlock(
            path="seed.py",
            search="def subtract(a, b):\n    return a - b\n",
            replace="def subtract(a, b):\n    return a - b - 0\n",
        )
        summary = apply_blocks([blk], repo)
        assert not summary.ok
        assert "did not match" in summary.results[0].reason

    def test_ambiguous_match_refuses(self, tmp_path):
        from maverick.edit_format import SearchReplaceBlock, apply_blocks
        repo = _make_git_repo(tmp_path)
        (repo / "seed.py").write_text("x = 1\nx = 1\n")
        blk = SearchReplaceBlock(path="seed.py", search="x = 1\n", replace="x = 2\n")
        summary = apply_blocks([blk], repo)
        assert not summary.ok
        assert "matches 2" in summary.results[0].reason
        # File must be unchanged.
        assert (repo / "seed.py").read_text() == "x = 1\nx = 1\n"

    def test_new_file_via_empty_search(self, tmp_path):
        from maverick.edit_format import SearchReplaceBlock, apply_blocks
        repo = _make_git_repo(tmp_path)
        blk = SearchReplaceBlock(
            path="new_dir/new_file.py",
            search="",
            replace="x = 42\n",
        )
        summary = apply_blocks([blk], repo)
        assert summary.ok
        assert summary.results[0].match_kind == "created"
        assert (repo / "new_dir" / "new_file.py").read_text() == "x = 42\n"

    def test_atomic_rollback_on_partial_fail(self, tmp_path):
        from maverick.edit_format import SearchReplaceBlock, apply_blocks
        repo = _make_git_repo(tmp_path)
        original = (repo / "seed.py").read_text()
        blk_ok = SearchReplaceBlock(
            path="seed.py",
            search="def add(a, b):\n    return a + b\n",
            replace="def add(a, b):\n    return a + b + 1\n",
        )
        blk_fail = SearchReplaceBlock(
            path="seed.py",
            search="this does not exist\n",
            replace="anything\n",
        )
        summary = apply_blocks([blk_ok, blk_fail], repo, atomic=True)
        assert not summary.ok
        # File must be restored to original.
        assert (repo / "seed.py").read_text() == original

    def test_path_traversal_blocked(self, tmp_path):
        from maverick.edit_format import SearchReplaceBlock, apply_blocks
        repo = _make_git_repo(tmp_path)
        blk = SearchReplaceBlock(
            path="../escape.py",
            search="",
            replace="oops\n",
        )
        summary = apply_blocks([blk], repo)
        assert not summary.ok
        assert "escape" in summary.results[0].reason

    def test_render_diff_after_apply(self, tmp_path):
        from maverick.edit_format import (
            SearchReplaceBlock, apply_blocks, render_diff,
        )
        repo = _make_git_repo(tmp_path)
        blk = SearchReplaceBlock(
            path="seed.py",
            search="def add(a, b):\n    return a + b\n",
            replace="def add(a, b):\n    return a + b + 1\n",
        )
        summary = apply_blocks([blk], repo)
        assert summary.ok
        diff = render_diff(repo)
        assert diff.startswith("diff --git")
        assert "-    return a + b" in diff
        assert "+    return a + b + 1" in diff


# ---- repair prompt ----

class TestRepairPrompt:
    def test_repair_prompt_includes_block_path_and_reason(self, tmp_path):
        from maverick.edit_format import (
            SearchReplaceBlock, ApplyResult, repair_prompt_for_failure,
        )
        result = ApplyResult(
            ok=False,
            block=SearchReplaceBlock(path="foo.py", search="x", replace="y"),
            reason="SEARCH block did not match",
            near_miss_context="closest match (line 5):\n   5: x = 1",
        )
        out = repair_prompt_for_failure(result)
        assert "foo.py" in out
        assert "did not match" in out
        assert "closest match" in out
        assert "<<<<<<< SEARCH" in out
        assert ">>>>>>> REPLACE" in out
