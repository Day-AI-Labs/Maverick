"""Q2 2026 batch 5: apply_patch, compute (sympy), email, pandas_query, git_advanced, cosign workflow."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------- apply_patch ----------

def test_apply_patch_requires_patch():
    from maverick.tools.apply_patch import apply_patch

    class _Sandbox:
        workdir = "."

    out = apply_patch(_Sandbox()).fn({"patch": ""})
    assert "patch is required" in out


def test_apply_patch_rejects_path_traversal(tmp_path):
    if not _git_available():
        pytest.skip("git not installed")
    _make_git_repo(tmp_path)
    (tmp_path / "a").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True)
    from maverick.tools.apply_patch import apply_patch

    class _Sandbox:
        workdir = str(tmp_path)

    bad_patch = (
        "diff --git a/../etc/passwd b/../etc/passwd\n"
        "--- a/../etc/passwd\n"
        "+++ b/../etc/passwd\n"
        "@@ -1 +1 @@\n"
        "-hi\n+pwned\n"
    )
    out = apply_patch(_Sandbox()).fn({"patch": bad_patch})
    assert "path-traversal" in out


def test_apply_patch_dry_run_lists_files(tmp_path):
    if not _git_available():
        pytest.skip("git not installed")
    _make_git_repo(tmp_path)
    (tmp_path / "a.txt").write_text("line1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True)
    (tmp_path / "a.txt").write_text("line1\nline2\n")
    proc = subprocess.run(
        ["git", "-C", str(tmp_path), "diff"], capture_output=True, check=True,
    )
    patch_text = proc.stdout.decode()
    # Reset so the patch applies cleanly against the worktree.
    subprocess.run(
        ["git", "-C", str(tmp_path), "checkout", "--", "a.txt"], check=True,
    )

    from maverick.tools.apply_patch import apply_patch

    class _Sandbox:
        workdir = str(tmp_path)

    out = apply_patch(_Sandbox()).fn({"patch": patch_text, "dry_run": True})
    assert "DRY RUN" in out
    assert "a.txt" in out


def test_apply_patch_applies_real_patch(tmp_path):
    if not _git_available():
        pytest.skip("git not installed")
    _make_git_repo(tmp_path)
    (tmp_path / "a.txt").write_text("line1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True)
    (tmp_path / "a.txt").write_text("line1\nline2\n")
    proc = subprocess.run(
        ["git", "-C", str(tmp_path), "diff"], capture_output=True, check=True,
    )
    patch_text = proc.stdout.decode()
    subprocess.run(
        ["git", "-C", str(tmp_path), "checkout", "--", "a.txt"], check=True,
    )
    assert (tmp_path / "a.txt").read_text() == "line1\n"

    from maverick.tools.apply_patch import apply_patch

    class _Sandbox:
        workdir = str(tmp_path)

    out = apply_patch(_Sandbox()).fn({"patch": patch_text})
    assert "applied to 1 file" in out
    assert (tmp_path / "a.txt").read_text() == "line1\nline2\n"


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _make_git_repo(p: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    subprocess.run(["git", "-C", str(p), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(p), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(p), "config", "commit.gpgsign", "false"], check=True)
    subprocess.run(["git", "-C", str(p), "config", "tag.gpgsign", "false"], check=True)


# ---------- compute (sympy) ----------

_HAS_SYMPY = importlib.util.find_spec("sympy") is not None


def test_compute_evaluate_simple():
    from maverick.tools.compute import compute
    out = compute().fn({"op": "evaluate", "expr": "2 + 3 * 4"})
    assert "14" in out


def test_compute_evaluate_with_pi_e():
    """Without sympy we still have math.pi via the fallback evaluator."""
    from maverick.tools.compute import compute
    out = compute().fn({"op": "evaluate", "expr": "pi"})
    # 3.141... whether via sympy.N or math.pi.
    assert "3.14" in out


@pytest.mark.skipif(not _HAS_SYMPY, reason="sympy not installed")
def test_compute_simplify():
    from maverick.tools.compute import compute
    out = compute().fn({"op": "simplify", "expr": "(x**2 - 1)/(x - 1)"})
    assert "x" in out
    assert "+ 1" in out or "1 + x" in out


@pytest.mark.skipif(not _HAS_SYMPY, reason="sympy not installed")
def test_compute_solve_quadratic():
    from maverick.tools.compute import compute
    out = compute().fn({"op": "solve", "equation": "x**2 - 4 = 0", "var": "x"})
    assert "x ∈" in out
    assert "-2" in out and "2" in out


@pytest.mark.skipif(not _HAS_SYMPY, reason="sympy not installed")
def test_compute_diff():
    from maverick.tools.compute import compute
    out = compute().fn({"op": "diff", "expr": "x**3", "var": "x"})
    assert "3" in out and "x" in out


@pytest.mark.skipif(not _HAS_SYMPY, reason="sympy not installed")
def test_compute_sympy_rejects_arbitrary_code():
    from maverick.tools.compute import compute
    out = compute().fn({"op": "simplify", "expr": "__import__('os').system('id')"})
    assert "ERROR" in out


def test_compute_unknown_op_rejected():
    from maverick.tools.compute import compute
    out = compute().fn({"op": "factorial"})
    assert "unknown op" in out


def test_compute_evaluate_rejects_arbitrary_code():
    """The fallback evaluator must refuse imports / attribute access."""
    if _HAS_SYMPY:
        pytest.skip("sympy installed; tests the unsafe path explicitly")
    from maverick.tools.compute import compute
    out = compute().fn({"op": "evaluate", "expr": "__import__('os')"})
    assert "ERROR" in out


# ---------- email tool ----------

def test_email_requires_op():
    from maverick.tools.email_tool import email_tool
    assert "op is required" in email_tool().fn({})


def test_email_send_requires_recipient(monkeypatch):
    monkeypatch.delenv("MAVERICK_EMAIL_DISABLE", raising=False)
    monkeypatch.setenv("EMAIL_USER", "me@example.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "pw")
    from maverick.tools.email_tool import email_tool
    out = email_tool().fn({"op": "send", "to": ""})
    assert "requires `to`" in out


def test_email_send_kill_switch(monkeypatch):
    monkeypatch.setenv("MAVERICK_EMAIL_DISABLE", "1")
    from maverick.tools.email_tool import email_tool
    out = email_tool().fn({"op": "send", "to": "x@y.com", "subject": "s"})
    assert "disabled" in out


def test_email_send_requires_credentials(monkeypatch):
    monkeypatch.delenv("MAVERICK_EMAIL_DISABLE", raising=False)
    monkeypatch.delenv("EMAIL_USER", raising=False)
    monkeypatch.delenv("EMAIL_APP_PASSWORD", raising=False)
    monkeypatch.setenv("HOME", "/nonexistent-home-for-tests")
    from maverick.tools.email_tool import email_tool
    out = email_tool().fn({
        "op": "send", "to": "x@y.com", "subject": "s", "body": "b",
    })
    assert "EMAIL_USER" in out


def test_email_send_via_smtp_ssl(monkeypatch):
    monkeypatch.delenv("MAVERICK_EMAIL_DISABLE", raising=False)
    monkeypatch.setenv("EMAIL_USER", "me@example.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "pw")
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.test")
    monkeypatch.setenv("EMAIL_SMTP_PORT", "465")

    fake_smtp = MagicMock()
    fake_smtp.__enter__ = MagicMock(return_value=fake_smtp)
    fake_smtp.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP_SSL", return_value=fake_smtp):
        from maverick.tools.email_tool import email_tool
        out = email_tool().fn({
            "op": "send", "to": "you@example.com",
            "subject": "Hello", "body": "Test",
        })
    assert "sent to you@example.com" in out
    fake_smtp.login.assert_called_once_with("me@example.com", "pw")
    fake_smtp.send_message.assert_called_once()


# ---------- pandas_query ----------

_HAS_PANDAS = importlib.util.find_spec("pandas") is not None


def test_pandas_query_requires_source():
    from maverick.tools.pandas_query import pandas_query
    assert "source is required" in pandas_query().fn({"op": "head"})


def test_pandas_query_missing_file(tmp_path):
    from maverick.tools.pandas_query import pandas_query
    out = pandas_query().fn({
        "op": "head",
        "source": str(tmp_path / "missing.csv"),
    })
    assert "file not found" in out


@pytest.mark.skipif(not _HAS_PANDAS, reason="pandas not installed")
def test_pandas_query_head_csv(tmp_path):
    csv_path = tmp_path / "people.csv"
    csv_path.write_text("name,age\nAlice,30\nBob,25\nCarol,40\n")
    from maverick.tools.pandas_query import pandas_query
    out = pandas_query().fn({"op": "head", "source": str(csv_path), "n": 2})
    assert "Alice" in out
    assert "Bob" in out
    assert "Carol" not in out


@pytest.mark.skipif(not _HAS_PANDAS, reason="pandas not installed")
def test_pandas_query_where_filter(tmp_path):
    csv_path = tmp_path / "people.csv"
    csv_path.write_text("name,age\nAlice,30\nBob,25\nCarol,40\n")
    from maverick.tools.pandas_query import pandas_query
    out = pandas_query().fn({
        "op": "head", "source": str(csv_path),
        "where": "age > 28",
    })
    assert "Alice" in out
    assert "Carol" in out
    assert "Bob" not in out


def test_pandas_query_rejects_bad_where(tmp_path):
    if not _HAS_PANDAS:
        pytest.skip("pandas not installed")
    csv_path = tmp_path / "p.csv"
    csv_path.write_text("a,b\n1,2\n")
    from maverick.tools.pandas_query import pandas_query
    out = pandas_query().fn({
        "op": "head", "source": str(csv_path),
        "where": "df.eval('a + b')",
    })
    assert "bad where clause" in out


def test_pandas_query_confines_path_to_sandbox_workspace(tmp_path):
    """With a sandbox wired in, an absolute path outside workdir is refused
    before any file is read (no arbitrary host-file read). Needs no pandas:
    the path check happens before load."""
    class _SB:
        workdir = tmp_path / "ws"

    (tmp_path / "ws").mkdir()
    secret = tmp_path / "secret.csv"
    secret.write_text("col\nvalue\n")

    from maverick.tools.pandas_query import pandas_query
    tool = pandas_query(_SB())
    out = tool.fn({"op": "head", "source": str(secret)})
    assert "escapes the workspace" in out
    # A traversal attempt is likewise refused.
    assert "escapes the workspace" in tool.fn({"op": "head", "source": "../secret.csv"})


@pytest.mark.skipif(not _HAS_PANDAS, reason="pandas not installed")
def test_pandas_query_caps_oversized_input(tmp_path, monkeypatch):
    """A file larger than the load cap is truncated, not read in full."""
    import maverick.tools.pandas_query as pq
    monkeypatch.setattr(pq, "_MAX_LOAD_ROWS", 5)
    csv_path = tmp_path / "big.csv"
    rows = "\n".join(f"r{i},{i}" for i in range(50))
    csv_path.write_text("name,val\n" + rows + "\n")

    out = pq.pandas_query().fn({"op": "head", "source": str(csv_path), "n": 100})
    assert "truncated to the first 5 rows" in out


# ---------- git_advanced ----------

def test_git_advanced_requires_repo(tmp_path):
    from maverick.tools.git_advanced import git_advanced

    class _Sandbox:
        workdir = str(tmp_path)

    out = git_advanced(_Sandbox()).fn({"op": "bisect_start"})
    assert "not a git repo" in out


def test_git_advanced_log_oneline(tmp_path):
    if not _git_available():
        pytest.skip("git not installed")
    _make_git_repo(tmp_path)
    (tmp_path / "a.txt").write_text("v1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "first"], check=True)
    (tmp_path / "a.txt").write_text("v2\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "second"], check=True)

    from maverick.tools.git_advanced import git_advanced

    class _Sandbox:
        workdir = str(tmp_path)

    out = git_advanced(_Sandbox()).fn({"op": "log_oneline", "limit": 5})
    assert "[log] OK" in out
    assert "first" in out and "second" in out


def test_git_advanced_cherry_pick_requires_commit(tmp_path):
    if not _git_available():
        pytest.skip("git not installed")
    _make_git_repo(tmp_path)
    (tmp_path / "a").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True)
    from maverick.tools.git_advanced import git_advanced

    class _Sandbox:
        workdir = str(tmp_path)

    out = git_advanced(_Sandbox()).fn({"op": "cherry_pick"})
    assert "requires commit" in out


def test_git_advanced_unknown_op(tmp_path):
    if not _git_available():
        pytest.skip("git not installed")
    _make_git_repo(tmp_path)
    (tmp_path / "a").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True)
    from maverick.tools.git_advanced import git_advanced

    class _Sandbox:
        workdir = str(tmp_path)

    out = git_advanced(_Sandbox()).fn({"op": "garbage"})
    assert "unknown op" in out


# ---------- registry ----------

def test_q2b5_tools_registered():
    from maverick.tools import base_registry

    class _FakeSandbox:
        workdir = "."

    class _FakeWorld:
        pass

    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())
    names = {t.name for t in reg.all()}
    for expected in (
        "apply_patch", "compute", "email",
        "pandas_query", "git_advanced",
    ):
        assert expected in names, f"missing tool: {expected}"


# ---------- cosign workflow ----------

def test_cosign_signing_in_publish_workflow():
    p = REPO_ROOT / ".github" / "workflows" / "publish.yml"
    body = p.read_text()
    assert "sigstore/cosign-installer" in body
    assert "cosign sign-blob" in body
    assert "id-token: write" in body
    # The sign job is gated on tag pushes.
    assert "refs/tags/v" in body
