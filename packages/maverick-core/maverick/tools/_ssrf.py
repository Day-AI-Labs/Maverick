"""SSRF-safe HTTP fetching: resolve once, validate, pin the connection.

Every tool that fetches a model/user-supplied URL used to do this::

    if is_blocked_host(parsed.hostname): reject
    httpx.get(url)              # <-- httpx re-resolves the name here

That is a DNS-rebinding TOCTOU: a hostile resolver can answer with a
public IP for the validation lookup and then ``127.0.0.1`` /
``169.254.169.254`` for the connection lookup, slipping past the guard.

This module closes the window. ``resolve_pinned_ip`` resolves the host
**once**, requires *every* returned address to be public, and returns the
IP. ``safe_client`` / ``safe_get`` then connect to that exact IP via a
transport that rewrites only the connection target, leaving the ``Host``
header and TLS SNI / certificate verification bound to the original
hostname. There is no second resolution, so there is nothing to rebind.

Honors ``MAVERICK_FETCH_ALLOW_PRIVATE=1`` (skips the public-only check but
still pins the resolved IP), matching the existing guard's escape hatch.

Redirects are NOT followed by default: a 3xx to a fresh host would not be
pinned, so callers must keep ``follow_redirects=False`` and re-validate
each hop themselves.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:  # pragma: no cover
    import httpx


class BlockedHost(Exception):
    """Raised when a URL's host won't resolve or resolves to a non-public IP."""


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable address -> refuse
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _allow_private() -> bool:
    return os.environ.get("MAVERICK_FETCH_ALLOW_PRIVATE") == "1"


def resolve_pinned_ip(host: str) -> str:
    """Resolve ``host`` once and return a single IP to connect to.

    Requires *every* resolved address to be public (so a resolver can't
    smuggle a private IP alongside a public one). Raises ``BlockedHost`` on
    a resolution failure or any non-public address.
    """
    if not host:
        raise BlockedHost("missing host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise BlockedHost(f"cannot resolve {host!r}: {e}") from e
    ips = [info[4][0] for info in infos if info[4]]
    if not ips:
        raise BlockedHost(f"no addresses for {host!r}")
    if not _allow_private():
        for ip in ips:
            if _ip_is_blocked(ip):
                raise BlockedHost(
                    f"{host!r} resolves to non-public address {ip}"
                )
    return ips[0]


def _request_host_matches(request: Any, host: str) -> bool:
    """True if ``request``'s host reconciles with the validated/pinned ``host``.

    httpx decodes an IDN host to Unicode in ``url.host`` while ``urlparse`` keeps
    the original (often punycode) form, so a naive ``url.host == host`` skips the
    pin for IDN hosts -- reopening the DNS-rebinding TOCTOU. Match either the
    Unicode or the ASCII/punycode (``raw_host``) form so a legitimate IDN host is
    still recognized and pinned, and anything that doesn't reconcile is refused."""
    candidates = {request.url.host}
    try:
        raw = request.url.raw_host
        if raw:
            candidates.add(raw.decode("ascii"))
    except Exception:
        pass
    return host in candidates


class _PinnedTransport:
    """httpx transport wrapper that connects to a pre-validated IP.

    Rewrites the request's connection host to ``ip`` while restoring the
    original ``Host`` header and setting ``sni_hostname`` so TLS SNI and
    certificate hostname verification stay bound to the real host.
    """

    def __init__(self, host: str, host_header: str, ip: str, inner: Any):
        self._host = host
        self._host_header = host_header
        self._ip = ip
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if not _request_host_matches(request, self._host):
            # Host doesn't reconcile with the validated/pinned host -- refuse
            # rather than let the inner transport re-resolve an unvalidated name.
            raise BlockedHost(
                f"unpinned host {request.url.host!r} != validated {self._host!r}")
        request.headers["Host"] = self._host_header
        request.extensions = {**request.extensions, "sni_hostname": self._host}
        request.url = request.url.copy_with(host=self._ip)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()

    def __enter__(self) -> _PinnedTransport:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def safe_client(url: str, **client_kwargs: Any) -> httpx.Client:
    """Return an ``httpx.Client`` pinned to a validated public IP for ``url``.

    Raises ``BlockedHost`` if the scheme is not http/https or the host
    resolves to a non-public address. ``follow_redirects`` defaults to
    ``False`` (see module docstring); callers re-validate redirects.
    """
    import httpx

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedHost(f"scheme {parsed.scheme!r} not allowed")
    host = parsed.hostname or ""
    ip = resolve_pinned_ip(host)
    host_header = host if not parsed.port else f"{host}:{parsed.port}"
    transport = _PinnedTransport(host, host_header, ip, httpx.HTTPTransport())
    client_kwargs.setdefault("follow_redirects", False)
    client_kwargs["transport"] = transport
    return httpx.Client(**client_kwargs)


def safe_get(url: str, **kwargs: Any) -> httpx.Response:
    """SSRF-safe ``httpx.get``: validates + pins the host, then fetches.

    Splits httpx ``Client`` kwargs (timeout, headers, verify, ...) from
    request kwargs (params, ...). Raises ``BlockedHost`` on a non-public
    host. Always uses ``follow_redirects=False``.
    """
    timeout = kwargs.pop("timeout", 30.0)
    headers = kwargs.pop("headers", None)
    verify = kwargs.pop("verify", True)
    # Drop any caller-supplied follow_redirects: a per-request True would
    # override the safe client's redirect-disabled default and let a 3xx escape
    # to an unpinned/unvalidated host -- the exact SSRF this helper prevents.
    kwargs.pop("follow_redirects", None)
    with safe_client(url, timeout=timeout, verify=verify) as client:
        return client.get(url, headers=headers, **kwargs)


class _AsyncPinnedTransport:
    """Async mirror of ``_PinnedTransport`` for ``httpx.AsyncClient``.

    Same contract: rewrite the connection host to the pre-validated IP while
    restoring the original ``Host`` header and TLS SNI, so there is no second
    name resolution to rebind.
    """

    def __init__(self, host: str, host_header: str, ip: str, inner: Any):
        self._host = host
        self._host_header = host_header
        self._ip = ip
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not _request_host_matches(request, self._host):
            raise BlockedHost(
                f"unpinned host {request.url.host!r} != validated {self._host!r}")
        request.headers["Host"] = self._host_header
        request.extensions = {**request.extensions, "sni_hostname": self._host}
        request.url = request.url.copy_with(host=self._ip)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def __aenter__(self) -> _AsyncPinnedTransport:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()


def safe_async_client(url: str, **client_kwargs: Any) -> httpx.AsyncClient:
    """Async counterpart of ``safe_client``: an ``httpx.AsyncClient`` pinned
    to a validated public IP for ``url``.

    Raises ``BlockedHost`` if the scheme is not http/https or the host
    resolves to a non-public address. ``follow_redirects`` defaults to
    ``False`` -- a 3xx to a fresh host would not be pinned.
    """
    import httpx

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedHost(f"scheme {parsed.scheme!r} not allowed")
    host = parsed.hostname or ""
    ip = resolve_pinned_ip(host)
    host_header = host if not parsed.port else f"{host}:{parsed.port}"
    transport = _AsyncPinnedTransport(host, host_header, ip, httpx.AsyncHTTPTransport())
    client_kwargs.setdefault("follow_redirects", False)
    client_kwargs["transport"] = transport
    return httpx.AsyncClient(**client_kwargs)


__all__ = [
    "BlockedHost",
    "resolve_pinned_ip",
    "safe_client",
    "safe_async_client",
    "safe_get",
]
