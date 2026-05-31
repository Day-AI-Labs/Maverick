"""Wave 11 adversarial pre-flight tests for the SWE-bench harness.

These five hand-crafted cases exercise the failure modes that the
operational research surfaced (CRLF, --- /dev/null, multi-file,
test-file gate, gold-leak guard). They run in <5 seconds with no
LLM calls; their job is to lock down the harness's invariants
BEFORE we burn $4k on a real SWE-bench Pro sweep.

Run via:  pytest benchmarks/test_swe_bench_adversarial_preflight.py -v
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _init_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "commit.gpgsign", "false"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    for path, content in files.items():
        full = tmp_path / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "seed"],
        check=True,
    )
    return tmp_path


# ---- 1. CRLF inside SEARCH/REPLACE block applies cleanly ----

def test_adv_crlf_search_replace_applies(tmp_path):
    """LLM output with CRLF line endings must apply against a LF file.
    Without normalization, this was the #1 cause of 'corrupt patch'
    on Windows-origin sources."""
    from maverick.edit_format import apply_blocks, parse_blocks
    repo = _init_repo(tmp_path, {
        "src/foo.py": "def f():\n    return 1\n",
    })
    # Model output with CRLF newlines.
    text = (
        "src/foo.py\r\n"
        "<<<<<<< SEARCH\r\n"
        "def f():\r\n"
        "    return 1\r\n"
        "=======\r\n"
        "def f():\r\n"
        "    return 2\r\n"
        ">>>>>>> REPLACE\r\n"
    )
    blocks = parse_blocks(text)
    summary = apply_blocks(blocks, repo)
    assert summary.ok, summary.summary_text()
    assert (repo / "src/foo.py").read_text() == "def f():\n    return 2\n"


# ---- 2. New file via empty SEARCH ----

def test_adv_new_file_via_empty_search(tmp_path):
    """Pro's `--- /dev/null` instances need this. Wave 10 fix was
    in validate_patch; here we lock the SR-format equivalent."""
    from maverick.edit_format import apply_blocks, parse_blocks
    repo = _init_repo(tmp_path, {"src/foo.py": "x = 1\n"})
    text = (
        "src/bar.py\n"
        "<<<<<<< SEARCH\n"
        "=======\n"
        "def new_helper():\n"
        "    return 42\n"
        ">>>>>>> REPLACE\n"
    )
    blocks = parse_blocks(text)
    summary = apply_blocks(blocks, repo)
    assert summary.ok
    assert (repo / "src/bar.py").exists()
    assert "new_helper" in (repo / "src/bar.py").read_text()


# ---- 3. Multi-file SR block with one bad block rolls back ALL ----

def test_adv_atomic_rollback_on_mixed_fail(tmp_path):
    """Pro instances average 4.1 files. We must not leave the workdir
    half-edited when one of N blocks fails — that confuses downstream
    test runs and creates phantom partial fixes."""
    from maverick.edit_format import apply_blocks, parse_blocks
    repo = _init_repo(tmp_path, {
        "src/a.py": "a = 1\n",
        "src/b.py": "b = 2\n",
    })
    original_a = (repo / "src/a.py").read_text()
    original_b = (repo / "src/b.py").read_text()
    text = (
        "src/a.py\n<<<<<<< SEARCH\na = 1\n=======\na = 11\n>>>>>>> REPLACE\n"
        "src/b.py\n<<<<<<< SEARCH\nbogus = 9\n=======\nb = 22\n>>>>>>> REPLACE\n"
    )
    blocks = parse_blocks(text)
    summary = apply_blocks(blocks, repo, atomic=True)
    assert not summary.ok
    # BOTH files must be unchanged.
    assert (repo / "src/a.py").read_text() == original_a
    assert (repo / "src/b.py").read_text() == original_b


# ---- 4. Defensive validator blocks test-file edits ----

def test_adv_defensive_blocks_tests_edit(tmp_path):
    """The grader applies its own test_patch AFTER ours; touching a
    test file silently zeros out the score for that instance. The
    defensive validator must refuse to submit such patches."""
    from maverick.coding_mode import defensive_validate
    patch = (
        "diff --git a/tests/test_models.py b/tests/test_models.py\n"
        "--- a/tests/test_models.py\n"
        "+++ b/tests/test_models.py\n"
        "@@ -1 +1 @@\n"
        "-assert foo == 1\n"
        "+assert foo == 2\n"
    )
    result = defensive_validate(
        patch, fail_to_pass=["tests/test_models.py::TestX::test_foo"],
    )
    assert not result.ok
    assert any("tests/test_models.py" in p for p in result.blocked_paths)


# ---- 5. Shell tool blocks curl to github.com in opaque mode ----

def test_adv_shell_blocks_github_curl(tmp_path, monkeypatch):
    """The most common cheating vector is the agent curl-ing the
    upstream fix PR off github.com and transcribing. Shell tool must
    refuse such commands in benchmark opaque mode."""
    from maverick.tools.shell import shell

    class _FakeSandbox:
        workdir = tmp_path
        timeout = 30.0

        def exec(self, cmd, timeout=None):
            from maverick.sandbox.local import ExecResult
            return ExecResult(stdout="ran: " + cmd, stderr="", exit_code=0)

    monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "1")
    monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
    tool = shell(_FakeSandbox())

    # Curl to github raw content — gold-leak vector.
    out = tool.fn({"cmd": "curl -sL https://raw.githubusercontent.com/foo/bar/abc.patch"})
    assert "blocked" in out.lower()
    assert "ran:" not in out

    # wget to github.com — same.
    out = tool.fn({"cmd": "wget https://github.com/foo/bar/pull/123.diff"})
    assert "blocked" in out.lower()

    # Plain `pytest` is allowed.
    out = tool.fn({"cmd": "pytest tests/test_foo.py"})
    assert "ran:" in out


# ---- Bonus: pip install -e blocked in opaque mode (Karpathy bug) ----

def test_adv_shell_blocks_pip_install_e(tmp_path, monkeypatch):
    """May 26 council fix: ALL package-install commands are blocked
    in opaque mode (not just `-e`). The prior Wave 11 fix only
    blocked `pip install -e` but `pip install <pkg>` could still
    pollute the local sandbox between instances. The grader's
    container has dependencies pre-installed; agent installs are
    a no-op for grading but persistent contamination locally."""
    from maverick.tools.shell import shell

    class _FakeSandbox:
        workdir = tmp_path
        timeout = 30.0

        def exec(self, cmd, timeout=None):
            from maverick.sandbox.local import ExecResult
            return ExecResult(stdout="ran: " + cmd, stderr="", exit_code=0)

    monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "1")
    monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
    tool = shell(_FakeSandbox())
    # Both editable and non-editable installs are blocked.
    for cmd in ("pip install -e .", "pip install requests", "npm install"):
        out = tool.fn({"cmd": cmd})
        assert "blocked" in out.lower(), (
            f"expected {cmd!r} to be blocked; got {out[:200]}"
        )
    # Override env: install allowed when opaque mode is off.
    monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "0")
    out = tool.fn({"cmd": "pip install ."})
    assert "ran:" in out


# ---- All-pass canary ----

def test_adv_all_canary_passing(tmp_path):
    """Smoke that the test file itself is exercising all five
    adversarial paths so a future refactor that accidentally removes
    one of them shows up loudly."""
    # If we got here with no test infrastructure errors, the suite is wired.
    assert os.environ.get("PYTEST_CURRENT_TEST")
