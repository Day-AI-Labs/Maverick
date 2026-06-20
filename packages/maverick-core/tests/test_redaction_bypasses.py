"""Regression tests for redaction bypasses in the PII / secret detectors.

Each test pins a specific evasion that previously leaked sensitive data into
logs / model context:
  #2 credit card concatenated with extra digits (>=20 digit run)
  #5 secret detector stopping at the first space of a quoted value
  #7 AWS secret-key separator window too narrow for aligned config
"""
from __future__ import annotations

from maverick.safety import pii_detector as pii
from maverick.safety import secret_detector as sec


def _kinds(text):
    return {m.kind for m in pii.scan(text)}


def _names(text):
    return {m.name for m in sec.scan(text)}


# --- #2 credit-card concatenation -------------------------------------------

def test_card_embedded_in_longer_digit_run_is_redacted():
    # Valid Visa test card (4242...4242) concatenated with a trailing order id.
    # The old \b...{13,19}\b matched NOTHING for a >=20 digit run.
    blob = "42424242424242420000"
    assert "credit_card" in _kinds(blob)
    redacted, _ = pii.redact(f"order {blob} shipped")
    assert blob not in redacted


def test_normal_card_still_redacted():
    assert "credit_card" in _kinds("4111 1111 1111 1111")
    assert "credit_card" in _kinds("4111-1111-1111-1111")


def test_non_card_digit_runs_not_redacted():
    # A 13-digit non-card and a Luhn-invalid 16-digit number must NOT be flagged
    # (no new false positives for normal-length runs).
    assert "credit_card" not in _kinds("1234567890123")
    assert "credit_card" not in _kinds("4111 1111 1111 1112")


# --- #5 quoted secret value --------------------------------------------------

def test_quoted_secret_value_fully_redacted():
    text = 'API_TOKEN="my secret value here"'
    spans = [m for m in sec.scan(text) if m.name == "env_secret"]
    assert spans, "env_secret not detected"
    a, b = spans[0].span
    assert text[a:b] == '"my secret value here"', "value span must cover the whole quoted string"
    redacted, _ = sec.redact(text)
    assert "secret value here" not in redacted


def test_single_quoted_and_unquoted_values():
    assert "secret" not in sec.redact("PASSWORD='hunter two'")[0]
    # Unquoted value behaviour unchanged: token up to first whitespace.
    red, matches = sec.redact("DB_PASSWORD=hunter2 and more")
    assert any(m.name == "env_secret" for m in matches)
    assert "hunter2" not in red


# --- #7 AWS secret-key separator width --------------------------------------

def test_aws_secret_with_wide_separator_redacted():
    key = "A" * 40
    assert "aws_secret_access" in _names("aws_secret_access_key        " + key)  # 8 spaces
    assert "aws_secret_access" in _names("aws_secret_access_key=" + key)         # tight
