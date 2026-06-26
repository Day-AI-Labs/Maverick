"""Email inbound authentication: classify SPF/DKIM so a spoofed From is dropped.

The allowlist gate trusts the IMAP `From` verbatim, which is forgeable; when the
receiving server has evaluated SPF/DKIM and it explicitly failed, the message is
rejected before it can impersonate an allowlisted sender. A domain that
publishes no records yields no verdict and is left to the allowlist (inherent
IMAP limitation).
"""
from __future__ import annotations

import email

import pytest
from maverick_channels.email import _authentication_verdict


def _msg(*auth_results: str):
    raw = "From: alice@example.com\r\n"
    for ar in auth_results:
        raw += f"Authentication-Results: {ar}\r\n"
    raw += "Subject: hi\r\n\r\nbody\r\n"
    return email.message_from_string(raw)


def test_pass_when_spf_or_dkim_pass():
    assert _authentication_verdict(
        _msg("mx.google.com; spf=pass smtp.mailfrom=example.com")) == "pass"
    # A DKIM pass wins even if SPF softfailed (common for forwarded mail).
    assert _authentication_verdict(
        _msg("mx; dkim=pass header.d=example.com; spf=softfail")) == "pass"


def test_fail_on_explicit_spf_or_dkim_failure():
    assert _authentication_verdict(
        _msg("mx.google.com; spf=fail smtp.mailfrom=evil.com")) == "fail"
    assert _authentication_verdict(_msg("mx; spf=softfail; dkim=none")) == "fail"
    assert _authentication_verdict(_msg("mx; dkim=fail; spf=none")) == "fail"


def test_none_when_no_results_or_only_neutral():
    # No Authentication-Results header at all (server didn't evaluate).
    assert _authentication_verdict(_msg()) == "none"
    # A domain without SPF/DKIM published: neutral/none -> not an explicit fail.
    assert _authentication_verdict(_msg("mx; spf=neutral; dkim=none")) == "none"


def test_forged_lower_header_cannot_mask_trusted_fail():
    # RFC 8601: the receiving MX prepends its own result, so the genuine verdict
    # is the TOPMOST header. A sender who controls their outbound headers can
    # add a lower 'Authentication-Results: ...; spf=pass'; joining all headers
    # let that forged pass mask the trusted MX's spf=fail. The verdict must stay
    # 'fail' -- only the topmost (trusted) header is honored.
    m = _msg(
        "mx.victim.com; spf=fail smtp.mailfrom=evil.com; dkim=none",
        "relay.attacker.com; spf=pass smtp.mailfrom=evil.com",
    )
    assert _authentication_verdict(m) == "fail"


def test_topmost_header_decides_verdict():
    # Topmost says pass -> pass, regardless of a lower forged fail.
    m = _msg(
        "mx.victim.com; spf=pass smtp.mailfrom=example.com",
        "relay.attacker.com; spf=fail smtp.mailfrom=example.com",
    )
    assert _authentication_verdict(m) == "pass"


def test_trusted_authserv_id_selects_matching_header(monkeypatch):
    # When EMAIL_TRUSTED_AUTHSERV_ID is configured, only the header stamped by
    # that authserv-id is honored -- even if a forged header is prepended above.
    monkeypatch.setenv("EMAIL_TRUSTED_AUTHSERV_ID", "mx.victim.com")
    m = _msg(
        "relay.attacker.com; spf=pass smtp.mailfrom=evil.com",
        "mx.victim.com; spf=fail smtp.mailfrom=evil.com; dkim=none",
    )
    assert _authentication_verdict(m) == "fail"


def test_trusted_authserv_id_absent_yields_none(monkeypatch):
    # If no header carries our trusted authserv-id, trust nobody -> 'none'.
    monkeypatch.setenv("EMAIL_TRUSTED_AUTHSERV_ID", "mx.victim.com")
    m = _msg("relay.attacker.com; spf=pass smtp.mailfrom=evil.com")
    assert _authentication_verdict(m) == "none"


@pytest.mark.parametrize("n_decoys", [1, 5, 25])
def test_many_forged_pass_decoys_cannot_starve_trusted_fail(n_decoys):
    # Order-independence: any number of forged spf=pass decoys below the trusted
    # MX's spf=fail must not flip the verdict.
    decoys = [f"relay{i}.attacker.com; spf=pass" for i in range(n_decoys)]
    m = _msg("mx.victim.com; spf=fail smtp.mailfrom=evil.com", *decoys)
    assert _authentication_verdict(m) == "fail"
