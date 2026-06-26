"""Regression tests for two redactor gaps found in the platform defect audit.

[1] safety.secret_detector.env_secret matched only `KEY=value`, silently missing
    colon-delimited `KEY: value` (YAML / k8s manifests / many logs) that its
    documented mirror maverick.secrets.env_secret already caught.
[6] maverick.secrets.private_key required an `-----END...-----` marker, so a PEM
    truncated by a buffer/summary boundary leaked its base64 body to logs.
"""
from __future__ import annotations

from maverick.safety.secret_detector import redact as sd_redact
from maverick.secrets import scrub


def test_secret_detector_redacts_colon_delimited_secret():
    # YAML / k8s style. Previously leaked because the separator was `=` only.
    # Plain value (no sk-/aws- prefix) so it can only be caught by env_secret.
    red, matches = sd_redact("API_TOKEN: plainvalue9876543210abc")
    assert "plainvalue9876543210abc" not in red
    assert any(m.name == "env_secret" for m in matches)


def test_secret_detector_still_redacts_equals_form():
    red, _ = sd_redact("DB_PASSWORD=hunter2hunter2hunter2")
    assert "hunter2hunter2hunter2" not in red


def test_secret_detector_and_secrets_agree_on_colon():
    # The two redactors are advertised as mirrors; both must catch the colon form.
    payload = "INTERNAL_API_KEY: abcdEFGH1234567890zz"
    assert "abcdEFGH1234567890zz" not in sd_redact(payload)[0]
    assert "abcdEFGH1234567890zz" not in scrub(payload)


def test_secrets_redacts_truncated_pem_without_end_marker():
    # A key cut off by a buffer/summary boundary: BEGIN header + body, no END.
    pem = ("-----BEGIN RSA PRIVATE KEY-----\n"
           "MIIEowIBAAKCAQEAtruncatedKeyBodyAAAA1234567890\n"
           "...buffer cut here, no END marker...")
    out = scrub(pem)
    assert "MIIEowIBAAKCAQEAtruncatedKeyBodyAAAA1234567890" not in out


def test_secrets_still_redacts_complete_pem():
    pem = ("-----BEGIN PRIVATE KEY-----\n"
           "ABCDEFbody123456\n"
           "-----END PRIVATE KEY-----")
    assert "ABCDEFbody123456" not in scrub(pem)
