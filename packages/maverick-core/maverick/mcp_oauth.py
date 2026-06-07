"""OAuth 2.1 client-credentials token provider for remote MCP servers (B2).

The static-bearer path (`[mcp_servers.<name>] auth_token`) works when you already
hold a long-lived token. For servers behind an OAuth 2.1 authorization server,
this fetches a short-lived access token via the **client_credentials** grant
(machine-to-machine — no user redirect), caches it, and refreshes before expiry.

The token fetch is injectable (`fetch=`) so the provider unit-tests against a
mock token endpoint with no network; production uses an https POST. Validated
end-to-end only against a real authorization server — the protocol logic here is
unit-tested in isolation.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

# Refresh this many seconds before the token actually expires, to absorb clock
# skew + request latency.
_EXPIRY_SKEW_S = 60.0
_DEFAULT_TTL_S = 3600.0


@dataclass(frozen=True)
class OAuthConfig:
    token_url: str
    client_id: str
    client_secret: str = ""
    scope: str = ""
    grant_type: str = "client_credentials"

    @classmethod
    def from_dict(cls, d: dict) -> OAuthConfig:
        if not isinstance(d, dict):
            raise ValueError("oauth config must be a table")
        token_url = str(d.get("token_url") or "").strip()
        client_id = str(d.get("client_id") or "").strip()
        if not token_url or not client_id:
            raise ValueError("oauth requires token_url and client_id")
        if not token_url.startswith("https://"):
            raise ValueError(f"oauth token_url must be https://, got {token_url!r}")
        grant = str(d.get("grant_type") or "client_credentials").strip()
        if grant != "client_credentials":
            raise ValueError(
                f"only the client_credentials grant is supported, got {grant!r}")
        return cls(
            token_url=token_url,
            client_id=client_id,
            client_secret=str(d.get("client_secret") or ""),
            scope=str(d.get("scope") or ""),
            grant_type=grant,
        )


def _default_fetch(cfg: OAuthConfig) -> dict:
    """POST the client_credentials grant to the token endpoint. https-only.

    The token_url is operator config (not model-controlled), so an https scheme
    check is the sanity guard here — same posture as the MCP server `url`."""
    import json
    import urllib.parse
    import urllib.request
    data = {"grant_type": cfg.grant_type, "client_id": cfg.client_id}
    if cfg.client_secret:
        data["client_secret"] = cfg.client_secret
    if cfg.scope:
        data["scope"] = cfg.scope
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        cfg.token_url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 -- https-checked
        return json.loads(r.read(100_000).decode("utf-8"))


class OAuthTokenProvider:
    """Cache + refresh an OAuth access token. Thread-safe; ``token()`` is sync."""

    def __init__(self, cfg: OAuthConfig, *, fetch=None):
        self._cfg = cfg
        self._fetch = fetch or _default_fetch
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._expires_at = 0.0

    def token(self, *, now: float | None = None) -> str:
        """Return a valid access token, fetching/refreshing if needed."""
        now = time.time() if now is None else now
        with self._lock:
            if self._access_token and now < self._expires_at - _EXPIRY_SKEW_S:
                return self._access_token
            resp = self._fetch(self._cfg)
            if not isinstance(resp, dict) or not resp.get("access_token"):
                raise ValueError(
                    "oauth token endpoint did not return an access_token")
            self._access_token = str(resp["access_token"])
            try:
                ttl = float(resp.get("expires_in", _DEFAULT_TTL_S))
            except (TypeError, ValueError):
                ttl = _DEFAULT_TTL_S
            self._expires_at = now + max(0.0, ttl)
            return self._access_token


__all__ = ["OAuthConfig", "OAuthTokenProvider"]
