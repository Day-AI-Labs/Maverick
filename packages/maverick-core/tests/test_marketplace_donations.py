"""Donate-direct: strict allowlist validation of donation links. Pure/offline."""
from __future__ import annotations

import pytest
from maverick.marketplace.donations import (
    MAX_URL_LENGTH,
    donation_info,
    validate_donation_url,
)


@pytest.mark.parametrize("url", [
    "https://ko-fi.com/cday",
    "https://www.ko-fi.com/cday",
    "https://opencollective.com/maverick",
    "https://liberapay.com/cday/donate",
    "https://buymeacoffee.com/cday",
    "https://github.com/sponsors/cday",
    "https://www.github.com/sponsors/cday",
])
def test_allowlisted_hosts_validate(url):
    ok, reason = validate_donation_url(url)
    assert ok, reason


@pytest.mark.parametrize("url,why", [
    ("http://ko-fi.com/cday", "https"),                       # plaintext
    ("ftp://ko-fi.com/cday", "https"),                        # wrong scheme
    ("https://evil.example.com/pay", "allowlist"),            # unknown host
    ("https://github.com/cday", "sponsors"),                  # not /sponsors/
    ("https://github.com/sponsors", "sponsors"),              # no sponsoree
    ("https://github.com.evil.com/sponsors/cday", "allowlist"),  # suffix spoof
    ("https://ko-fi.com.evil.com/cday", "allowlist"),         # suffix spoof
    ("https://ko-fi.com@evil.com/cday", "credentials"),       # userinfo trick
    ("https://ko-fi.com:8443/cday", "port"),                  # pinned port
    ("https://sub.ko-fi.com/cday", "allowlist"),              # subdomain
    ("https://ko-fi.com/c day", "whitespace"),                # embedded space
    ("https://ko-fi.com/x\n", "whitespace"),                  # control char
    ("", "non-empty"),
    (None, "non-empty"),
    (42, "non-empty"),
    ("https://ko-fi.com/" + "a" * MAX_URL_LENGTH, "longer"),
])
def test_everything_else_is_rejected(url, why):
    ok, reason = validate_donation_url(url)
    assert not ok
    assert why in reason


def test_donation_info_surfaces_listing_field():
    assert donation_info({"name": "x"}) is None
    assert donation_info({"donation_url": ""}) is None

    good = donation_info({"donation_url": "https://ko-fi.com/cday"})
    assert good == {"url": "https://ko-fi.com/cday", "ok": True, "reason": "ok"}

    bad = donation_info({"donation_url": "https://evil.com/x"})
    assert bad is not None and not bad["ok"]
    assert "allowlist" in bad["reason"]


def test_donation_info_accepts_objects_with_attribute():
    class Listing:
        donation_url = "https://liberapay.com/cday"

    info = donation_info(Listing())
    assert info is not None and info["ok"]
    # And objects without the attribute (e.g. CatalogEntry) -> None.
    assert donation_info(object()) is None


def test_links_only_no_payment_processing():
    """The module must stay a validator: no HTTP client, no checkout flow."""
    import maverick.marketplace.donations as mod
    doc = mod.__doc__ or ""
    assert "No payment processing" in doc
    src_names = set(dir(mod))
    assert not src_names & {"httpx", "requests", "urlopen"}
