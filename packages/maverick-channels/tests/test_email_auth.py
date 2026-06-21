"""Email inbound authentication: classify SPF/DKIM so a spoofed From is dropped.

The allowlist gate trusts the IMAP `From` verbatim, which is forgeable; when the
receiving server has evaluated SPF/DKIM and it explicitly failed, the message is
rejected before it can impersonate an allowlisted sender. A domain that
publishes no records yields no verdict and is left to the allowlist (inherent
IMAP limitation).
"""
from __future__ import annotations

import email

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
