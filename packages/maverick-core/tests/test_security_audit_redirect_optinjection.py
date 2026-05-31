"""Regression tests for the multi-pass security audit fixes.

Covers four findings:
  1. SSRF: guarded_urlopen must re-validate redirect targets, not just the
     entry URL (a public host could 302 to the cloud metadata endpoint).
  2. git_advanced: LLM-controlled refs/paths starting with ``-`` are git
     option injection (e.g. ``git show --output=...`` writes a file) and
     must be rejected even though shlex.quote stops shell metacharacters.
  3. secret_detector: generically-named env secrets (INTERNAL_API_TOKEN=...)
     must be redacted before they reach the audit log / model context.
  4. shield: tool-call gating must catch ``rm -rf /`` / ``rm -rf ~`` in
     structured args (the old repr()-based payload broke the rule anchor).
"""
from __future__ import annotations

import pytest

# ---------- 1. SSRF redirect revalidation ----------

def test_guarded_urlopen_revalidates_redirect_to_metadata(monkeypatch):
    from maverick.tools import http_fetch

    handler = http_fetch._RevalidatingRedirectHandler(allow_http=True)

    class _Req:
        def get_full_url(self):
            return "https://example.com/"

    # A 302 to the cloud metadata endpoint must be refused mid-redirect.
    with pytest.raises(ValueError):
        handler.redirect_request(
            _Req(), None, 302, "Found", {},
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        )


def test_guarded_urlopen_allows_redirect_to_public(monkeypatch):
    from maverick.tools import http_fetch

    monkeypatch.setattr(http_fetch, "is_blocked_host", lambda _h: False)
    handler = http_fetch._RevalidatingRedirectHandler(allow_http=False)

    class _Req:
        def get_full_url(self):
            return "https://example.com/"

        def get_method(self):
            return "GET"

        @property
        def headers(self):
            return {}

        unredirected_hdrs: dict = {}
        data = None
        origin_req_host = "example.com"
        unverifiable = False

    # A redirect to a normal public https URL is allowed (returns a Request).
    out = handler.redirect_request(
        _Req(), None, 302, "Found", {}, "https://other.example.org/next",
    )
    assert out is not None


# ---------- 2. git option injection ----------

class _FakeSandbox:
    def __init__(self, workdir):
        self.workdir = workdir

    def exec(self, cmd, timeout=None):
        class _R:
            exit_code = 0
            stdout = cmd
            stderr = ""
        return _R()


@pytest.fixture
def _git_run(tmp_path):
    (tmp_path / ".git").mkdir()
    from maverick.tools.git_advanced import _make_run
    return _make_run(_FakeSandbox(tmp_path))


@pytest.mark.parametrize("args", [
    {"op": "show_commit", "commit": "--output=/tmp/pwn"},
    {"op": "cherry_pick", "commit": "-x"},
    {"op": "rebase_onto", "onto": "--exec=touch /tmp/x", "upstream": "main"},
    {"op": "worktree_add", "path": "--foo"},
    {"op": "log_oneline", "since_ref": "--all"},
    {"op": "bisect_good", "ref": "-x"},
])
def test_git_advanced_rejects_option_like_args(_git_run, args):
    out = _git_run(args)
    assert out.startswith("ERROR: refusing option-like argument")


def test_git_advanced_accepts_normal_ref(_git_run):
    out = _git_run({"op": "show_commit", "commit": "HEAD"})
    assert "show HEAD" in out and "OK" in out


# ---------- 3. secret_detector generic env secret ----------

@pytest.mark.parametrize("text", [
    "INTERNAL_API_TOKEN=zzz-internal-token-value-1234",
    "export DB_PASSWORD=correcthorsebatterystaple",
    "MY_CUSTOM_SECRET=hunter2supersecretvalue",
])
def test_secret_detector_redacts_generic_env_secret(text):
    from maverick.safety.secret_detector import redact
    out, matches = redact(text)
    assert matches and "[REDACTED:env_secret]" in out
    # The raw value must be gone; the var name stays for readability.
    assert "=" in out
    assert out.split("=", 1)[1] == "[REDACTED:env_secret]"


def test_secret_detector_ignores_non_secret_assignment():
    from maverick.safety.secret_detector import redact
    out, matches = redact("LOG_LEVEL=debug\nMAX_RETRIES=5")
    assert not matches and out == "LOG_LEVEL=debug\nMAX_RETRIES=5"


# ---------- 4. shield tool-call gating ----------

@pytest.mark.parametrize("cmd", ["rm -rf /", "rm -rf ~", "rm -rf $HOME"])
def test_shield_scan_tool_call_blocks_destructive_rm(cmd):
    from maverick_shield.guard import Shield
    sh = Shield(backend=Shield.BACKEND_BUILTIN)
    verdict = sh.scan_tool_call("shell", {"cmd": cmd})
    assert not verdict.allowed
    assert verdict.severity == "critical"


def test_shield_scan_tool_call_allows_benign():
    from maverick_shield.guard import Shield
    sh = Shield(backend=Shield.BACKEND_BUILTIN)
    assert sh.scan_tool_call("shell", {"cmd": "ls -la /tmp"}).allowed
