"""best-of-N workdir capture + reset helpers.

When a coding agent edits files via tools but emits no diff in its final answer,
run_goal_best_of_n must recover the on-disk work as the candidate patch (so it
isn't silently lost), and must isolate each attempt by resetting the shared
workdir to clean HEAD. These cover the two helpers directly with real git repos.
"""
from __future__ import annotations

import subprocess
import tempfile

from maverick.orchestrator import (
    _capture_workdir_diff,
    _reset_workdir_to_head,
    _strip_binary_diff_sections,
)


def _git(d, *args):
    return subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True)


def _init_repo(d, files: dict):
    d.mkdir(parents=True, exist_ok=True)
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@t.t")
    _git(d, "config", "user.name", "t")
    _git(d, "config", "core.autocrlf", "false")  # keep CRLF bytes verbatim
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "init")


def _applies_to_head(repo, diff: str) -> bool:
    """Mirror evaluate_candidate: a worktree checked out at HEAD + git apply."""
    wt = tempfile.mkdtemp()
    _git(repo, "worktree", "add", "--detach", wt, "HEAD")
    try:
        r = subprocess.run(["git", "-C", wt, "apply", "--check", "-"],
                           input=diff.encode(), capture_output=True)
        return r.returncode == 0
    finally:
        _git(repo, "worktree", "remove", "--force", wt)


def test_capture_includes_modified_and_new_files(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo, {"solution.py": b"def f():\n    raise NotImplementedError\n"})
    # agent edits via tools: modify tracked file + create a NEW untracked file
    (repo / "solution.py").write_bytes(b"def f():\n    return 42\n")
    (repo / "helper.py").write_bytes(b"X = 1\n")
    diff = _capture_workdir_diff(repo)
    assert "solution.py" in diff and "return 42" in diff
    assert "helper.py" in diff and "/dev/null" in diff       # new file as a hunk
    assert _applies_to_head(repo, diff)                       # round-trips to HEAD


def test_capture_crlf_file_applies(tmp_path):
    """Regression for the verifier's MAJOR finding: a git diff of a CRLF file
    must NOT be CR-normalized, or git apply rejects it."""
    repo = tmp_path / "r"
    _init_repo(repo, {"f.txt": b"a\r\nb\r\nc\r\n"})
    (repo / "f.txt").write_bytes(b"a\r\nMODIFIED\r\nc\r\n")
    diff = _capture_workdir_diff(repo)
    assert diff
    assert _applies_to_head(repo, diff)                       # fails if \r stripped


def test_capture_excludes_pycache_and_still_applies(tmp_path):
    """Regression for the live bug: running the candidate's tests creates
    __pycache__/*.pyc; without a .gitignore, `git add -A` would stage them and
    git renders 'Binary files ... differ', which makes `git apply` reject the
    WHOLE patch. The capture must exclude them and still apply."""
    repo = tmp_path / "r"
    _init_repo(repo, {"solution.py": b"def f():\n    raise NotImplementedError\n"})
    (repo / "solution.py").write_bytes(b"def f():\n    return 7\n")
    # stray compiled bytecode left by a test run (binary, untracked, not ignored)
    pyc = repo / "__pycache__"
    pyc.mkdir()
    (pyc / "solution.cpython-311.pyc").write_bytes(b"\x00\x01\x02\xfe\xff binary")
    diff = _capture_workdir_diff(repo)
    assert "return 7" in diff
    assert ".pyc" not in diff and "Binary files" not in diff   # noise excluded
    assert _applies_to_head(repo, diff)                          # patch still valid


def test_strip_binary_diff_sections_drops_only_binary():
    text_section = (
        "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"
    )
    bin_section = (
        "diff --git a/y.bin b/y.bin\nindex 1..2 100644\nBinary files a/y.bin and b/y.bin differ\n"
    )
    out = _strip_binary_diff_sections(text_section + bin_section)
    assert "x.py" in out and "y.bin" not in out and "Binary files" not in out
    # no-op when there's nothing binary
    assert _strip_binary_diff_sections(text_section) == text_section


def test_capture_leaves_index_clean(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo, {"a.py": b"1\n"})
    (repo / "a.py").write_bytes(b"2\n")
    _capture_workdir_diff(repo)
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == ""


def test_capture_non_git_and_none_return_empty(tmp_path):
    assert _capture_workdir_diff(tmp_path / "nope") == ""
    assert _capture_workdir_diff(None) == ""


def test_capture_empty_when_no_changes(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo, {"a.py": b"1\n"})
    assert _capture_workdir_diff(repo) == ""


def test_reset_reverts_tracked_and_removes_untracked(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo, {"a.py": b"orig\n"})
    (repo / "a.py").write_bytes(b"changed\n")
    (repo / "new.py").write_bytes(b"junk\n")
    _reset_workdir_to_head(repo)
    assert (repo / "a.py").read_bytes() == b"orig\n"          # reverted
    assert not (repo / "new.py").exists()                     # untracked removed


def test_reset_preserves_gitignored_artifacts(tmp_path):
    """clean -fd (not -fdx) keeps git-ignored install artifacts (e.g. egg-info
    from `pip install -e .`) so imports survive between attempts."""
    repo = tmp_path / "r"
    _init_repo(repo, {"a.py": b"1\n", ".gitignore": b"*.egg-info/\n"})
    egg = repo / "pkg.egg-info"
    egg.mkdir()
    (egg / "PKG-INFO").write_bytes(b"meta\n")
    _reset_workdir_to_head(repo)
    assert (egg / "PKG-INFO").exists()                        # ignored -> preserved


def test_reset_non_git_is_noop(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    (d / "x").write_bytes(b"1\n")
    _reset_workdir_to_head(d)         # must not raise
    _reset_workdir_to_head(None)      # must not raise
    assert (d / "x").exists()
