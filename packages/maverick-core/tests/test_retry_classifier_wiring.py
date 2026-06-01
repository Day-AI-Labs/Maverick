"""retry_classifier wired into retry.py (#317).

A terminal error class (auth / content-filter / context-overflow) must
NOT be retried even when it arrives as one of the retryable provider
exception types or with no status code — retrying just burns attempts.
"""
from __future__ import annotations

import maverick.retry as retry


class _Authish(Exception):
    """A retryable-by-type-looking error whose message marks it terminal."""


class _Transient(Exception):
    pass


def test_terminal_auth_error_not_retried(monkeypatch):
    monkeypatch.setenv("MAVERICK_RETRY_CLASSIFY", "1")
    # Force our exception type onto the retryable set so the type guard
    # would otherwise allow a retry; the classifier must veto it.
    monkeypatch.setattr(retry, "_retryable_exception_classes", lambda: (_Authish,))
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise _Authish("401 Unauthorized: invalid api key")

    try:
        retry.sync_retry(fn)
    except _Authish:
        pass
    # Terminal -> exactly one attempt, no backoff loop.
    assert calls["n"] == 1


def test_content_filter_not_retried(monkeypatch):
    monkeypatch.setenv("MAVERICK_RETRY_CLASSIFY", "1")
    monkeypatch.setattr(retry, "_retryable_exception_classes", lambda: (_Authish,))
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise _Authish("request blocked by content policy / safety filter")

    try:
        retry.sync_retry(fn)
    except _Authish:
        pass
    assert calls["n"] == 1


def test_transient_still_retries(monkeypatch):
    monkeypatch.setenv("MAVERICK_RETRY_CLASSIFY", "1")
    monkeypatch.setattr(retry, "_retryable_exception_classes", lambda: (_Transient,))
    monkeypatch.setattr(retry, "MAX_ATTEMPTS", 3)
    monkeypatch.setattr(retry, "_compute_delay", lambda *a, **k: 0.0)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise _Transient("connection reset by peer")

    try:
        retry.sync_retry(fn)
    except _Transient:
        pass
    # Transient -> retried up to MAX_ATTEMPTS.
    assert calls["n"] == 3


def test_classifier_can_be_disabled(monkeypatch):
    monkeypatch.setenv("MAVERICK_RETRY_CLASSIFY", "0")
    monkeypatch.setattr(retry, "_retryable_exception_classes", lambda: (_Authish,))
    monkeypatch.setattr(retry, "MAX_ATTEMPTS", 3)
    monkeypatch.setattr(retry, "_compute_delay", lambda *a, **k: 0.0)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise _Authish("401 Unauthorized")

    try:
        retry.sync_retry(fn)
    except _Authish:
        pass
    # Classifier off -> falls back to type/status behavior -> retried.
    assert calls["n"] == 3
