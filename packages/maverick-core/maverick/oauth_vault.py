"""Per-tenant OAuth token vault — refresh tokens sealed at rest.

The OAuth helper (:mod:`maverick.tools.oauth_helper`) can capture access/refresh
tokens, but only ever wrote them to a plaintext ``MAVERICK_OAUTH_OUT`` file —
fine for a one-off capture, wrong for a hosted multi-tenant deployment where one
tenant's long-lived refresh token must never sit in cleartext or be readable
across tenants.

This vault stores each provider's token record **sealed under the tenant's own
DEK** (``tenant.kms.seal_text_for_tenant`` — AES-256-GCM envelope, one data key
per tenant) in a tenant-scoped ``oauth/tokens.sealed``. So a token at rest is
encrypted, and a wrapped DEK from one tenant can't open another's vault (the
KMS binds tenant id + purpose into the AEAD context).

It deliberately performs **no network**: refreshing an expired token is done by a
caller-supplied ``refresher`` callable (the OAuth helper already speaks the
token endpoint), and the vault just persists the rotated record. Opt-in and
offline-testable; fails closed if the ``cryptography`` extra is missing rather
than silently degrading to plaintext.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable

from .paths import data_dir
from .tenant.kms import seal_text_for_tenant, unseal_text_for_tenant

# Default clock skew (seconds) treated as "already expired" so a token isn't
# handed out moments before the provider rejects it.
_DEFAULT_SKEW = 60

_lock = threading.Lock()


def _expires_at_from(record: dict) -> float | None:
    """Absolute expiry epoch for a record. Honors an explicit ``expires_at``;
    otherwise derives it from ``expires_in`` + ``obtained_at`` (or now)."""
    if record.get("expires_at") is not None:
        try:
            return float(record["expires_at"])
        except (TypeError, ValueError):
            return None
    if record.get("expires_in") is not None:
        try:
            base = float(record.get("obtained_at", time.time()))
            return base + float(record["expires_in"])
        except (TypeError, ValueError):
            return None
    return None


def is_expired(record: dict, *, skew: int = _DEFAULT_SKEW, now: float | None = None) -> bool:
    """Whether ``record``'s access token is expired (or within ``skew`` of it).
    A record with no expiry information is treated as NOT expired."""
    exp = _expires_at_from(record)
    if exp is None:
        return False
    return (now if now is not None else time.time()) >= (exp - skew)


class OAuthVault:
    """Sealed, per-tenant store of OAuth token records keyed by provider.

    One sealed JSON blob per tenant maps ``provider -> record``; a record is the
    provider's token response (``access_token``, ``refresh_token``,
    ``expires_in``/``expires_at``, ``scope``, ...), plus a normalized
    ``obtained_at``. ``tenant_id`` defaults to the active tenant.
    """

    def __init__(self, tenant_id: str | None = "__active__") -> None:
        self._tenant_id = tenant_id

    # -- storage ------------------------------------------------------------
    def _path(self):
        if self._tenant_id == "__active__":
            return data_dir("oauth", "tokens.sealed")
        return data_dir("oauth", "tokens.sealed", tenant=self._tenant_id)

    def _seal_tenant(self) -> str | None:
        # seal_for_tenant takes a concrete tenant id (None = single-tenant /
        # default DEK); resolve the active tenant the same way data_dir does.
        if self._tenant_id == "__active__":
            from .paths import current_tenant
            return current_tenant()
        return self._tenant_id

    def _load(self) -> dict[str, dict]:
        path = self._path()
        if not path.exists():
            return {}
        try:
            raw = unseal_text_for_tenant(self._seal_tenant(), path.read_bytes())
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}

    def _save(self, data: dict[str, dict]) -> None:
        path = self._path()
        blob = seal_text_for_tenant(self._seal_tenant(), json.dumps(data, sort_keys=True))
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Atomic replace via a 0600 temp file so a crash can't leave a partial
        # (or world-readable) sealed vault.
        tmp = path.with_suffix(".sealed.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        os.replace(tmp, path)

    # -- public surface -----------------------------------------------------
    def put(self, provider: str, record: dict) -> None:
        """Store/overwrite ``provider``'s token record (sealed). Stamps
        ``obtained_at`` if absent so relative ``expires_in`` stays meaningful."""
        if not provider:
            raise ValueError("provider is required")
        rec = dict(record or {})
        rec.setdefault("obtained_at", time.time())
        with _lock:
            data = self._load()
            data[provider] = rec
            self._save(data)

    def get(self, provider: str) -> dict | None:
        """The stored record for ``provider`` (decrypted), or ``None``."""
        with _lock:
            return self._load().get(provider)

    def delete(self, provider: str) -> bool:
        """Remove ``provider``'s record. Returns whether one was present."""
        with _lock:
            data = self._load()
            existed = provider in data
            if existed:
                del data[provider]
                self._save(data)
            return existed

    def providers(self) -> list[str]:
        """Providers with a stored record (sorted)."""
        with _lock:
            return sorted(self._load())

    def access_token(
        self, provider: str, *,
        refresher: Callable[[dict], dict] | None = None,
        skew: int = _DEFAULT_SKEW,
    ) -> str | None:
        """A usable access token for ``provider``.

        If the stored token is still valid, return it. If it's expired (within
        ``skew``) and a ``refresher`` is supplied, call ``refresher(record)``,
        which must return the new token response; the rotated record is sealed
        back to the vault (preserving the existing ``refresh_token`` when the
        provider's response omits it, per the OAuth spec) and its access token
        returned. Returns ``None`` if there is no record, or it's expired and no
        refresher was given."""
        with _lock:
            data = self._load()
            record = data.get(provider)
            if record is None:
                return None
            if not is_expired(record, skew=skew):
                return record.get("access_token")
            if refresher is None:
                return None
            fresh = dict(refresher(record) or {})
            # Providers may omit the refresh token on refresh — keep the old one.
            if not fresh.get("refresh_token") and record.get("refresh_token"):
                fresh["refresh_token"] = record["refresh_token"]
            fresh.setdefault("obtained_at", time.time())
            data[provider] = fresh
            self._save(data)
            return fresh.get("access_token")


def enabled() -> bool:
    """Whether the sealed OAuth vault is the active token sink. Off by default;
    ``[oauth] vault`` / ``MAVERICK_OAUTH_VAULT`` turns it on. Never raises."""
    from .config import env_flag
    v = env_flag("MAVERICK_OAUTH_VAULT")
    if v is not None:
        return v
    try:
        from .config import load_config
        return bool((load_config() or {}).get("oauth", {}).get("vault", False))
    except Exception:  # pragma: no cover -- config must never block
        return False


def get_vault(tenant_id: str | None = "__active__") -> OAuthVault:
    """An :class:`OAuthVault` for the given (default: active) tenant."""
    return OAuthVault(tenant_id)


__all__: list[str] = [
    "OAuthVault", "is_expired", "enabled", "get_vault",
]
