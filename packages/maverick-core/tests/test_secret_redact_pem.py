"""A PEM private key must be redacted IN FULL, not just its header line.

Security finding (round 7, adversarial): the private_key_pem pattern matched
only `-----BEGIN ... PRIVATE KEY-----`, so redact() replaced just that marker
and left the base64 key body + END line in cleartext. A private key pasted
into a goal / tool output / the blackboard would persist its actual secret
material in the world model and displayed output with only the header redacted.
"""
from __future__ import annotations

from maverick.safety.secret_detector import redact

# Synthetic non-secret fixture body (the PEM regex matches the BEGIN..END
# structure, not the body content) -- detect-secrets entropy plugin flags it.
_KEY_BODY = (
    "MIIEpAIBAAKCAQEA7Xy2hZ9qF8s1J3kLmN0pQrStUvWxYz0123456789abcdef\n"  # pragma: allowlist secret
    "GHIJKLMNOPqrstuvwxyzABCDEFabcdef0123456789+/aaaaaaaaaaaaaaaaaa\n"  # pragma: allowlist secret
    "bbbbbbbbbbbbbbbbbbccccccccccccccccccddddddddddddddddddeeeeeeee=="  # pragma: allowlist secret
)


def _pem(kind: str = "RSA ") -> str:
    return (f"-----BEGIN {kind}PRIVATE KEY-----\n{_KEY_BODY}\n"  # pragma: allowlist secret
            f"-----END {kind}PRIVATE KEY-----")


def test_full_pem_block_is_fully_redacted():
    text = f"my key is:\n{_pem()}\nthanks"
    red, matches = redact(text)
    assert matches
    # None of the key material may survive.
    assert "MIIEpAIBAAKCAQEA" not in red
    assert "eeeeeeee==" not in red
    assert "-----END RSA PRIVATE KEY-----" not in red  # pragma: allowlist secret
    assert "-----BEGIN RSA PRIVATE KEY-----" not in red  # pragma: allowlist secret
    # Surrounding text is preserved.
    assert "my key is:" in red and "thanks" in red


def test_openssh_and_ec_keys_fully_redacted():
    for kind in ("OPENSSH ", "EC ", ""):
        red, _ = redact(_pem(kind))
        assert "MIIEpAIBAAKCAQEA" not in red, kind
        assert "eeeeeeee==" not in red, kind


def test_bare_begin_marker_without_end_still_flagged():
    # A truncated/malformed marker (no END) must still be caught, not ignored.
    red, matches = redact("-----BEGIN RSA PRIVATE KEY-----")  # pragma: allowlist secret
    assert matches
    assert "[REDACTED:" in red
