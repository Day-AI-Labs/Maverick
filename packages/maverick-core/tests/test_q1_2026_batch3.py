"""Q1 2026 batch 3: preflight, retry_classifier, wizard --fast."""
from __future__ import annotations

from pathlib import Path

import pytest

# ---------- preflight ----------

def test_preflight_context_limit_known_model():
    from maverick.preflight import context_limit
    assert context_limit("claude-opus-4-7") == 200_000
    assert context_limit("gpt-5.4-nano") == 32_000
    assert context_limit("kimi-k2") == 128_000


def test_preflight_context_limit_unknown_falls_back():
    from maverick.preflight import context_limit
    # Unknown id with no family prefix match -> 32k default.
    assert context_limit("totally-made-up-model-xyz") == 32_000


def test_preflight_estimate_tokens_zero_for_empty():
    from maverick.preflight import estimate_tokens
    assert estimate_tokens("") == 0


def test_preflight_estimate_tokens_grows_with_length():
    from maverick.preflight import estimate_tokens
    small = estimate_tokens("hi")
    big = estimate_tokens("hi " * 1000)
    assert big > small


def test_preflight_under_budget_succeeds():
    from maverick.preflight import preflight
    estimated = preflight(
        model="claude-sonnet-4-6",
        system="be brief",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=2048,
    )
    assert estimated > 0


def test_preflight_over_budget_strict_raises():
    from maverick.preflight import PreflightFailed, preflight
    # Build a payload bigger than the 32k default for unknown models.
    huge = "x" * 200_000
    with pytest.raises(PreflightFailed) as exc:
        preflight(
            model="unknown-model",
            system=huge,
            messages=[{"role": "user", "content": "ok"}],
            max_tokens=2048,
            strict=True,
        )
    err = exc.value
    assert err.estimated > 0
    assert err.limit == 32_000


def test_preflight_over_budget_non_strict_warns_but_returns():
    """strict=False: log warning instead of raising."""
    from maverick.preflight import preflight
    huge = "x" * 200_000
    est = preflight(
        model="unknown-model",
        system=huge,
        messages=[],
        max_tokens=2048,
        strict=False,
    )
    assert est > 0  # didn't raise


def test_preflight_tools_count_toward_estimate():
    from maverick.preflight import preflight
    tools = [{
        "name": "x",
        "description": "Y" * 5000,
        "input_schema": {"properties": {}},
    }]
    with_tools = preflight(
        model="claude-sonnet-4-6", system="", messages=[],
        tools=tools, max_tokens=2048, strict=False,
    )
    without_tools = preflight(
        model="claude-sonnet-4-6", system="", messages=[],
        tools=None, max_tokens=2048, strict=False,
    )
    assert with_tools > without_tools


# ---------- retry_classifier ----------

@pytest.mark.parametrize("err_msg,expected", [
    ("HTTPError: 429 Too Many Requests",           "rate_limit"),
    ("rate limit exceeded for model",              "rate_limit"),
    ("AuthenticationError: 401 Unauthorized",      "auth"),
    ("invalid api key provided",                   "auth"),
    ("RefusalError: content policy violation",     "content_filter"),
    ("Your request was refused due to safety",     "content_filter"),
    ("HTTPError: 500 Internal Server Error",       "server_5xx"),
    ("503 Service Unavailable",                    "server_5xx"),
    ("TimeoutError: Connection timed out",         "transient_network"),
    ("Connection refused on api.example.com",      "transient_network"),
    ("ContextLengthExceeded: maximum context",     "context_overflow"),
    ("prompt too long for window",                 "context_overflow"),
    ("JSONDecodeError: malformed response",        "malformed_response"),
])
def test_retry_classifier_substring_patterns(err_msg, expected):
    from maverick.retry.classifier import classify
    err = RuntimeError(err_msg)
    assert classify(err).value == expected


def test_retry_classifier_status_code_attr():
    """Some HTTP libraries put the status on the exception."""
    from maverick.retry.classifier import ErrorClass, classify

    class _HttpError(Exception):
        def __init__(self, code: int):
            super().__init__(f"HTTP {code}")
            self.status_code = code

    assert classify(_HttpError(429)) == ErrorClass.RATE_LIMIT
    assert classify(_HttpError(401)) == ErrorClass.AUTH
    assert classify(_HttpError(503)) == ErrorClass.SERVER_5XX


def test_retry_classifier_unknown_defaults():
    from maverick.retry.classifier import ErrorClass, classify
    assert classify(RuntimeError("weird unhelpful message")) == ErrorClass.UNKNOWN


def test_retry_classifier_should_retry_respects_max():
    from maverick.retry.classifier import should_retry
    err = RuntimeError("429 Too Many Requests")
    assert should_retry(err, attempts_so_far=0)
    assert should_retry(err, attempts_so_far=5)
    assert not should_retry(err, attempts_so_far=999)


def test_retry_classifier_terminal_errors_dont_retry():
    """Auth + content filter + context overflow are terminal."""
    from maverick.retry.classifier import should_retry
    assert not should_retry(RuntimeError("401 Unauthorized"), attempts_so_far=0)
    assert not should_retry(RuntimeError("content filter"), attempts_so_far=0)
    assert not should_retry(RuntimeError("context length exceeded"), attempts_so_far=0)


def test_retry_classifier_next_delay_grows():
    from maverick.retry.classifier import next_delay
    err = RuntimeError("Connection reset")  # transient_network
    d0 = next_delay(err, attempts_so_far=0)
    d3 = next_delay(err, attempts_so_far=3)
    assert 0 < d0 < d3


def test_retry_classifier_terminal_zero_delay():
    from maverick.retry.classifier import next_delay
    assert next_delay(RuntimeError("401 Unauthorized"), attempts_so_far=0) == 0.0


def test_retry_classifier_next_delay_is_jittered():
    # No jitter -> every caller hitting the same class at once retries in
    # lockstep (synchronized storm against a recovering provider). Delays must
    # be decorrelated and bounded to (0.5*base, base].
    from maverick.retry.classifier import next_delay
    err = RuntimeError("429 rate limit")  # rate_limit: base 10s at attempt 0
    samples = {next_delay(err, attempts_so_far=0) for _ in range(50)}
    assert len(samples) > 1                 # not deterministic
    assert all(5.0 <= d < 10.0 for d in samples)  # equal-jitter band of 10s


# ---------- wizard --fast flag ----------

def test_wizard_run_accepts_fast_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from maverick_installer import wizard
    # Patch CONFIG_DIR / FILES so we write to tmp_path.
    wizard.CONFIG_DIR = tmp_path / ".maverick"
    wizard.CONFIG_FILE = wizard.CONFIG_DIR / "config.toml"
    wizard.ENV_FILE = wizard.CONFIG_DIR / ".env"
    # Fast setup now picks the sandbox by Docker availability; pin it up so
    # this test deterministically exercises the full docker-config path.
    monkeypatch.setattr(wizard, "_docker_available", lambda: True)

    rc = wizard.run(fast=True)
    assert rc == 0
    # Config got written.
    assert wizard.CONFIG_FILE.exists()
    body = wizard.CONFIG_FILE.read_text()
    assert "[providers.anthropic]" in body
    assert "[safety]" in body
    assert "[sandbox]" in body
    assert "backend = \"docker\"" in body
    # ENV stored the key.
    assert wizard.ENV_FILE.exists()
    env_body = wizard.ENV_FILE.read_text()
    assert "ANTHROPIC_API_KEY=sk-ant-test" in env_body


def test_wizard_run_default_still_interactive(tmp_path, monkeypatch):
    """run() without fast=True should NOT short-circuit -- it'd ask."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # We can't actually drive an interactive session in tests, but
    # we can verify the function signature accepts the kwarg.
    import inspect

    from maverick_installer.wizard import run
    sig = inspect.signature(run)
    assert "fast" in sig.parameters
    assert sig.parameters["fast"].default is False


# ---------- CI workflows present ----------

def test_publish_workflow_exists():
    repo_root = Path(__file__).resolve().parents[3]
    assert (repo_root / ".github" / "workflows" / "publish.yml").is_file()


def test_conventional_commits_workflow_exists():
    repo_root = Path(__file__).resolve().parents[3]
    assert (repo_root / ".github" / "workflows" / "conventional-commits.yml").is_file()


def test_starter_goals_doc_exists():
    repo_root = Path(__file__).resolve().parents[3]
    # Moved out of docs/templates/ -> docs/ so MkDocs (which excludes the
    # templates/ dir) actually builds + serves the page. See fix/docs-accuracy.
    assert (repo_root / "docs" / "starter-goals.md").is_file()
