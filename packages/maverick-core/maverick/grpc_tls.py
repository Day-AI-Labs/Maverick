"""TLS / mTLS for the gRPC surfaces (goal API + federation).

Both gRPC servers historically bound ``add_insecure_port`` and the federation
client dialed ``insecure_channel`` — bearer tokens and cross-swarm goal text
(client data) crossed the wire in plaintext. This module builds gRPC
credentials from config so those listeners and channels can run TLS, with
optional **mTLS** (the server requires + verifies a client certificate).

Config (per section, ``grpc`` for the goal API and ``federation``)::

    [grpc]            # or [federation]
    tls = true                         # turn TLS on for this surface
    tls_cert = "/etc/maverick/tls/server.crt"
    tls_key  = "/etc/maverick/tls/server.key"
    tls_client_ca = "/etc/maverick/tls/clients-ca.crt"  # presence => mTLS
    # client side (dialing a federation peer):
    tls_ca = "/etc/maverick/tls/peer-ca.crt"            # verify the peer server
    tls_client_cert = "/etc/maverick/tls/client.crt"    # our cert for mTLS
    tls_client_key  = "/etc/maverick/tls/client.key"

**Fail-closed:** when the deployment is client-bound / enterprise (or
``tls_required = true``), a surface that cannot build server credentials refuses
to start, and the federation client refuses to dial a peer in the clear —
sensitive data never falls back to plaintext silently. When neither TLS nor a
requirement is configured, behaviour is unchanged (insecure, single-tenant dev).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}


def _section(name: str) -> dict:
    try:
        from .config import load_config
        return (load_config() or {}).get(name) or {}
    except Exception:  # pragma: no cover - config never blocks transport setup
        return {}


def _read(path: str | None) -> bytes | None:
    if not path:
        return None
    try:
        return Path(str(path)).expanduser().read_bytes()
    except OSError as e:
        raise TlsConfigError(f"cannot read TLS file {path!r}: {e}") from e


class TlsConfigError(RuntimeError):
    """TLS is required/enabled but the certificate material is unusable."""


def tls_enabled(section: str, cfg: dict | None = None) -> bool:
    """Has the operator turned TLS on for this surface (``[<section>] tls``)?"""
    c = cfg if cfg is not None else _section(section)
    return str(c.get("tls") or "").strip().lower() in _TRUE


def tls_required(section: str, cfg: dict | None = None) -> bool:
    """Is TLS MANDATORY for this surface?

    True when ``[<section>] tls_required`` is set, or the deployment is
    client-bound / enterprise (a real client's data must not cross the wire in
    plaintext). When true and credentials can't be built, the caller fails
    closed rather than falling back to an insecure port/channel.
    """
    c = cfg if cfg is not None else _section(section)
    if str(c.get("tls_required") or "").strip().lower() in _TRUE:
        return True
    try:
        from .client import client_binding_enforced
        return client_binding_enforced()
    except Exception:  # pragma: no cover
        return False


def server_credentials(section: str, cfg: dict | None = None) -> Any | None:
    """Build ``grpc.ServerCredentials`` for this surface, or ``None``.

    Returns ``None`` when TLS isn't enabled and isn't required. Raises
    :class:`TlsConfigError` when TLS is enabled/required but cert+key are
    missing/unreadable. A ``tls_client_ca`` enables mTLS (require + verify the
    client certificate against that CA).
    """
    c = cfg if cfg is not None else _section(section)
    if not tls_enabled(section, c):
        if tls_required(section, c):
            raise TlsConfigError(
                f"[{section}] TLS is required (client-bound/enterprise or "
                f"tls_required) but not configured; set [{section}] tls = true "
                f"with tls_cert/tls_key. Refusing to serve in plaintext."
            )
        return None
    cert = _read(c.get("tls_cert"))
    key = _read(c.get("tls_key"))
    if not cert or not key:
        raise TlsConfigError(
            f"[{section}] tls = true but tls_cert/tls_key are missing/unreadable."
        )
    import grpc
    client_ca = _read(c.get("tls_client_ca"))
    return grpc.ssl_server_credentials(
        [(key, cert)],
        root_certificates=client_ca,
        require_client_auth=client_ca is not None,  # mTLS when a client CA is pinned
    )


def channel_credentials(section: str, cfg: dict | None = None) -> Any | None:
    """Build ``grpc.ChannelCredentials`` for dialing this surface, or ``None``.

    ``None`` means dial insecure (only allowed when TLS isn't required).
    ``tls_ca`` pins the CA that signs the peer's server cert; ``tls_client_cert``
    /``tls_client_key`` present our certificate for mTLS.
    """
    c = cfg if cfg is not None else _section(section)
    if not tls_enabled(section, c):
        return None
    import grpc
    return grpc.ssl_channel_credentials(
        root_certificates=_read(c.get("tls_ca")),
        private_key=_read(c.get("tls_client_key")),
        certificate_chain=_read(c.get("tls_client_cert")),
    )


def bind_port(server: Any, address: str, section: str) -> bool:
    """Bind ``server`` to ``address`` with TLS when configured, else insecure.

    Returns True if the port is secure (TLS). Raises :class:`TlsConfigError`
    when TLS is required but unavailable (fail-closed). Logs a warning once on
    an insecure bind so an operator never ships plaintext unaware.
    """
    creds = server_credentials(section)  # raises if required-but-missing
    if creds is not None:
        server.add_secure_port(address, creds)
        log.info("%s gRPC bound with TLS on %s", section, address)
        return True
    server.add_insecure_port(address)
    log.warning("%s gRPC bound WITHOUT TLS on %s (plaintext) — set [%s] tls = "
                "true for production", section, address, section)
    return False


__all__ = [
    "TlsConfigError",
    "tls_enabled",
    "tls_required",
    "server_credentials",
    "channel_credentials",
    "bind_port",
]
