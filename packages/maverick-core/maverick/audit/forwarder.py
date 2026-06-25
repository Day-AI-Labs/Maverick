"""Push audit events to a SIEM endpoint (#56).

The pull-based ``maverick audit export`` re-emits the tamper-evident log as
JSONL/CEF to a file or stdout; this module is the *push* counterpart, shipping
those same rendered lines to a network collector so a SIEM ingests them without
a cron job scraping files off the box.

Three destination schemes, parsed from a single URI so one ``--to`` flag /
``[audit] siem_dest`` knob covers them:

  - ``tcp://host:port`` -- newline-framed syslog/TCP (Splunk, rsyslog, Vector).
  - ``udp://host:port`` -- one datagram per event (classic syslog/UDP).
  - ``http://...`` / ``https://...`` -- a single POST whose body is the
    newline-delimited batch (Splunk HEC ``/raw``, Sumo, an HTTP collector). A
    bearer from ``MAVERICK_SIEM_TOKEN`` (via the secret provider) is sent as
    ``Authorization`` when set.

Read-only with respect to the audit log: it only consumes already-rendered
event lines. Returns the count shipped. Best-effort framing, explicit errors --
a transport failure raises so the CLI exits non-zero (a SIEM gap is a
compliance event, not something to swallow).
"""
from __future__ import annotations

import logging
import socket
from collections.abc import Iterable
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_SUPPORTED = ("tcp", "udp", "http", "https")
# A datagram cap so one oversized event can't exceed a typical MTU-safe syslog
# payload; TCP/HTTP are stream/length-framed and not subject to it.
_UDP_MAX = 65507


def parse_dest(dest: str) -> tuple[str, str, int, str]:
    """Validate a destination URI -> ``(scheme, host, port, path)``.

    Raises ``ValueError`` on an unsupported scheme or a missing host/port for a
    socket scheme, so a typo in config fails loudly at startup instead of
    silently dropping audit traffic.
    """
    u = urlparse((dest or "").strip())
    scheme = (u.scheme or "").lower()
    if scheme not in _SUPPORTED:
        raise ValueError(
            f"unsupported SIEM destination scheme {scheme!r} "
            f"(expected one of {', '.join(_SUPPORTED)})"
        )
    if scheme in ("tcp", "udp"):
        if not u.hostname or not u.port:
            raise ValueError(f"{scheme} destination needs host:port (got {dest!r})")
        return scheme, u.hostname, int(u.port), ""
    if not u.hostname:
        raise ValueError(f"http(s) destination needs a host (got {dest!r})")
    return scheme, u.hostname, int(u.port or (443 if scheme == "https" else 80)), dest


def _siem_token() -> str | None:
    try:
        from ..secret_provider import get_secret
        tok = get_secret("MAVERICK_SIEM_TOKEN")
    except Exception:  # pragma: no cover -- never block forwarding on token lookup
        tok = None
    return tok.strip() if tok else None


def _send_tcp(host: str, port: int, lines: Iterable[str], timeout: float) -> int:
    n = 0
    with socket.create_connection((host, port), timeout=timeout) as sock:
        for line in lines:
            sock.sendall((line + "\n").encode("utf-8"))
            n += 1
    return n


def _send_udp(host: str, port: int, lines: Iterable[str], timeout: float) -> int:
    n = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        addr = (host, port)
        for line in lines:
            payload = (line + "\n").encode("utf-8")[:_UDP_MAX]
            sock.sendto(payload, addr)
            n += 1
    return n


def _send_http(url: str, lines: Iterable[str], timeout: float) -> int:
    import urllib.request

    batch = list(lines)
    if not batch:
        return 0
    body = ("\n".join(batch) + "\n").encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    token = _siem_token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - scheme validated
        code = getattr(resp, "status", None) or resp.getcode()
    if not (200 <= int(code) < 300):
        raise RuntimeError(f"SIEM HTTP collector returned {code}")
    return len(batch)


def forward(lines: Iterable[str], dest: str, *, timeout: float = 10.0) -> int:
    """Ship already-rendered audit lines to ``dest``; return the count sent.

    ``lines`` is any iterable of strings (e.g. ``to_jsonl``/``to_cef`` over
    ``iter_audit_events``). Raises on an unsupported/ malformed destination or a
    transport error so the caller can surface the gap.
    """
    scheme, host, port, url = parse_dest(dest)
    if scheme == "tcp":
        return _send_tcp(host, port, lines, timeout)
    if scheme == "udp":
        return _send_udp(host, port, lines, timeout)
    return _send_http(url, lines, timeout)


__all__ = ["forward", "parse_dest"]
