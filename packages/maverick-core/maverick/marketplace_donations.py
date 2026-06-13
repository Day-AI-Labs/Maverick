"""Marketplace donate-direct — validated donation *links* on listings.

Skill authors may declare a ``donation_url`` in their raw listing JSON (the
catalog index entry). This module validates it against a strict allowlist and
surfaces it for display. Scope, stated plainly:

  - **Links only. No payment processing.** Maverick never touches money,
    never proxies a checkout, never adds query parameters or referral codes.
    The validated URL is shown to the user; clicking it is between the user,
    their browser, and the platform.
  - ``donation_url`` is an *optional raw-listing field*. The typed
    :class:`maverick.catalog.CatalogEntry` deliberately does not model it
    (no catalog schema change); consumers read it from the raw listing dict
    via :func:`donation_info`. The federation import path
    (``marketplace_federation``) carries and re-validates it.
  - The moderation gauntlet (``maverick.tools.marketplace_moderation``) is a
    single pure ``_scan`` function with no pluggable checks list, so donation
    validation is NOT folded into it (restructuring it for one check isn't
    worth the churn). Composers run :func:`validate_donation_url` alongside
    the gauntlet — ``marketplace_federation.import_listings`` does exactly
    that, stripping invalid links.

Validation is fail-closed: https only, no userinfo, no explicit port, host
exactly on the allowlist (``www.`` tolerated), and ``github.com`` only under
``/sponsors/<name>``. Anything else is rejected.
"""
from __future__ import annotations

from urllib.parse import urlsplit

# Hosts whose whole purpose is creator funding. github.com is path-restricted
# below (only /sponsors/<name> is a donation page).
ALLOWED_HOSTS = frozenset({
    "ko-fi.com",
    "opencollective.com",
    "liberapay.com",
    "buymeacoffee.com",
})
_GITHUB_HOST = "github.com"
MAX_URL_LENGTH = 300


def _normalized_host(hostname: str | None) -> str:
    return (hostname or "").strip().lower().rstrip(".")


def validate_donation_url(url: object) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for a declared donation URL. Fail-closed."""
    if not isinstance(url, str) or not url:
        return False, "donation_url must be a non-empty string"
    if len(url) > MAX_URL_LENGTH:
        return False, f"donation_url longer than {MAX_URL_LENGTH} chars"
    if any(c.isspace() or ord(c) < 0x20 for c in url):
        return False, "donation_url contains whitespace or control characters"
    try:
        parts = urlsplit(url)
    except ValueError:
        return False, "donation_url is not a parseable URL"
    if parts.scheme != "https":
        return False, "donation_url must use https"
    if "@" in parts.netloc:
        return False, "donation_url must not embed credentials"
    try:
        if parts.port is not None:
            return False, "donation_url must not pin a port"
    except ValueError:
        return False, "donation_url has a malformed port"
    host = _normalized_host(parts.hostname)
    host = host.removeprefix("www.")
    if host in ALLOWED_HOSTS:
        return True, "ok"
    if host == _GITHUB_HOST:
        # Only the Sponsors surface, with an actual sponsoree name.
        segs = [s for s in parts.path.split("/") if s]
        if len(segs) >= 2 and segs[0] == "sponsors":
            return True, "ok"
        return False, "github.com donations must be a /sponsors/<name> URL"
    allowed = ", ".join(sorted(ALLOWED_HOSTS) + [_GITHUB_HOST + "/sponsors"])
    return False, f"host {host or '(none)'!r} is not on the donation allowlist ({allowed})"


def donation_info(listing: object) -> dict | None:
    """Donation link info for a raw listing dict (or any object with a
    ``donation_url`` attribute).

    Returns ``None`` when the listing declares no donation URL, otherwise
    ``{"url", "ok", "reason"}`` — display layers must only render the link
    when ``ok`` is true.
    """
    if isinstance(listing, dict):
        url = listing.get("donation_url")
    else:
        url = getattr(listing, "donation_url", None)
    if url is None or url == "":
        return None
    ok, reason = validate_donation_url(url)
    return {"url": url if isinstance(url, str) else str(url), "ok": ok, "reason": reason}


__all__ = ["ALLOWED_HOSTS", "MAX_URL_LENGTH", "validate_donation_url", "donation_info"]
