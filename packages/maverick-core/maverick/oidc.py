"""OIDC ID-token verification — the P4 SSO foundation for `maverick serve`.

Verifies an OpenID-Connect ID token (a JWT) against a configured issuer and
audience and returns a :class:`VerifiedPrincipal` whose ``principal`` id is
``f"user:{sub}"`` — the same convention the agent loop and capability layer
already use (see :func:`maverick.capability.capability_from_config` and
``agent.py``'s root-grant principal). So a verified SSO user drops straight
into the existing capability/tenant model with no new identity surface.

Security posture (these are load-bearing, not stylistic — get them wrong and
it's an auth bypass):

- The signature-algorithm allowlist is **asymmetric-only** (default
  ``["RS256","ES256"]``). ``none`` and every HMAC alg (``HS256/384/512``) are
  rejected. This defeats the classic *alg-confusion* attack, where an attacker
  re-signs a token with ``HS256`` using the *public* RSA key bytes as the HMAC
  secret; if a verifier accepts HMAC, the public key (which everyone has)
  becomes a forgery key. We never feed a symmetric verification path to PyJWT.
- ``exp``/``iat``/``aud``/``iss``/``sub`` are all *required* and verified
  (``options={"require": [...]}`` plus ``audience=``/``issuer=``). A token
  missing any of them is rejected.
- Signing keys are fetched from the JWKS endpoint keyed by the token header
  ``kid``; a ``kid`` absent from the JWKS is a rejection (no fallback key).
- On ANY failure we raise :class:`OIDCError`. We never return a principal on a
  partial/failed verification — there is no fail-open path to "authenticated".

Off by default. With ``[auth.oidc].enabled`` unset (and no ``MAVERICK_OIDC_*``
env), :func:`oidc_enabled` is False and nothing in the kernel requires a token —
behaviour is unchanged. This mirrors the opt-in pattern in
``capability.capability_enforced`` and ``paths.tenant_by_user_enabled``.

PyJWT (``pyjwt[crypto]``) is an *optional* dependency (extra ``oidc``); the
kernel imports fine without it. It's lazy-imported only when verification
actually runs, with an actionable install hint.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# Asymmetric signature algorithms only. HMAC (HS*) and "none" are
# deliberately absent and additionally hard-rejected below, regardless of
# config, so a misconfigured `[auth.oidc].algorithms` can never reopen the
# alg-confusion hole.
DEFAULT_ALGORITHMS = ["RS256", "ES256"]
_ALLOWED_ASYMMETRIC = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512", "EdDSA"}
)
_TRUE_VALUES = {"1", "true", "yes", "on"}


class OIDCError(Exception):
    """Raised on any OIDC verification or configuration failure.

    Subclasses :class:`Exception` (not anything that could be mistaken for
    success). Callers MUST treat this as "unauthenticated" — there is no
    code path that both raises this and returns a principal.
    """


@dataclass(frozen=True)
class VerifiedPrincipal:
    """A successfully verified OIDC subject, mapped to Maverick's identity.

    ``principal`` is ``f"user:{sub}"`` so it slots straight into the
    capability/tenant conventions; ``claims`` is the raw verified claim set
    (callers may read ``email``/``name``/etc., but trust only what the IdP
    actually signed)."""

    sub: str
    issuer: str
    audience: str
    claims: dict[str, Any] = field(default_factory=dict)

    @property
    def principal(self) -> str:
        return f"user:{self.sub}"


@dataclass(frozen=True)
class OIDCConfig:
    """Resolved ``[auth.oidc]`` settings."""

    enabled: bool = False
    issuer: str = ""
    audience: str = ""
    jwks_uri: str = ""
    algorithms: list[str] = field(default_factory=lambda: list(DEFAULT_ALGORITHMS))


def _env_flag(name: str) -> bool | None:
    """Tri-state env flag: True/False if set to a recognized value, else None
    (meaning "env says nothing; defer to config")."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in _TRUE_VALUES


def _load_oidc_section() -> dict:
    """Read the ``[auth.oidc]`` table from config, tolerating a missing or
    unreadable config (the kernel runs without one)."""
    try:
        from .config import load_config

        auth = (load_config() or {}).get("auth") or {}
        section = auth.get("oidc") or {}
        return section if isinstance(section, dict) else {}
    except Exception:
        return {}


def _normalize_algorithms(value: Any) -> list[str]:
    """Coerce a config/env value into a clean, asymmetric-only alg list.

    Drops anything that isn't an allowlisted asymmetric algorithm — so a
    hand-edited config that adds ``HS256`` or ``none`` silently loses it here,
    and :func:`verify_oidc_token` independently re-checks before calling PyJWT.
    """
    if isinstance(value, str):
        items = [p.strip() for p in value.split(",")]
    elif isinstance(value, (list, tuple)):
        items = [str(p).strip() for p in value]
    else:
        items = []
    algs = [a for a in items if a in _ALLOWED_ASYMMETRIC]
    return algs or list(DEFAULT_ALGORITHMS)


def load_oidc_config() -> OIDCConfig:
    """Resolve OIDC config from ``MAVERICK_OIDC_*`` env then ``[auth.oidc]``.

    Env overrides config per field. ``algorithms`` accepts a comma-separated
    env value or a TOML list; it is always normalized to asymmetric-only.
    """
    section = _load_oidc_section()

    enabled_env = _env_flag("MAVERICK_OIDC_ENABLED")
    enabled = enabled_env if enabled_env is not None else bool(section.get("enabled", False))

    issuer = os.environ.get("MAVERICK_OIDC_ISSUER") or str(section.get("issuer", "") or "")
    audience = os.environ.get("MAVERICK_OIDC_AUDIENCE") or str(section.get("audience", "") or "")
    jwks_uri = os.environ.get("MAVERICK_OIDC_JWKS_URI") or str(section.get("jwks_uri", "") or "")

    algs_raw: Any = os.environ.get("MAVERICK_OIDC_ALGORITHMS")
    if algs_raw is None:
        algs_raw = section.get("algorithms")
    algorithms = _normalize_algorithms(algs_raw)

    return OIDCConfig(
        enabled=enabled,
        issuer=issuer.strip(),
        audience=audience.strip(),
        jwks_uri=jwks_uri.strip(),
        algorithms=algorithms,
    )


def oidc_enabled() -> bool:
    """Opt-in, off by default. ``MAVERICK_OIDC_ENABLED=1`` or
    ``[auth.oidc] enabled = true`` turns on OIDC ID-token verification for the
    serving surface. Off -> no token is required and behaviour is unchanged."""
    return load_oidc_config().enabled


def _require_pyjwt():
    """Lazy-import PyJWT with an actionable error.

    The kernel must run without PyJWT installed; we only need it when actually
    verifying a token, so the import lives here rather than at module top."""
    try:
        import jwt  # noqa: F401
        return jwt
    except ModuleNotFoundError as e:
        raise OIDCError(
            "OIDC verification requires PyJWT, which isn't installed. "
            "Install the optional extra:  pip install 'maverick-agent[oidc]'  "
            "(or  pip install 'pyjwt[crypto]>=2.8' )."
        ) from e


def _safe_algorithms(config: OIDCConfig) -> list[str]:
    """The final algorithm allowlist handed to PyJWT.

    Defence in depth: even though config is normalized on load, we filter again
    to asymmetric-only here so no caller-built ``OIDCConfig`` (or future code
    path) can smuggle ``HS*``/``none`` into the verify call. If nothing
    survives, we raise rather than silently fall back — refusing to verify is
    the safe failure."""
    algs = [a for a in config.algorithms if a in _ALLOWED_ASYMMETRIC]
    if not algs:
        raise OIDCError(
            "no asymmetric signing algorithm configured; refusing to verify "
            "(HMAC/none are never accepted for OIDC)"
        )
    return algs


def _resolve_signing_key(
    jwt_mod,
    token: str,
    *,
    signing_key: Any,
    config: OIDCConfig,
):
    """Resolve the verification key.

    Order:
      1. An explicitly injected ``signing_key`` (a PEM/obj key, or a
         ``PyJWKClient``-like object exposing ``get_signing_key_from_jwt``) is
         used directly — this is the test seam, so no network is touched.
      2. Otherwise a :class:`jwt.PyJWKClient` is built from ``jwks_uri`` and the
         key is fetched by the token's header ``kid``. A ``kid`` not present in
         the JWKS raises (PyJWKClient raises ``PyJWKClientError``), which we
         convert to :class:`OIDCError`.
    """
    if signing_key is not None:
        # A resolver/JWK-client was injected: let it pick by kid.
        if hasattr(signing_key, "get_signing_key_from_jwt"):
            try:
                return signing_key.get_signing_key_from_jwt(token).key
            except Exception as e:  # PyJWKClientError, key-not-found, ...
                raise OIDCError(f"signing key resolution failed: {e}") from e
        # A raw key object / PEM string was injected (the common test path:
        # the local RSA public key). Use it as-is.
        return signing_key

    if not config.jwks_uri:
        raise OIDCError("OIDC jwks_uri is not configured")
    try:
        client = jwt_mod.PyJWKClient(config.jwks_uri)
        return client.get_signing_key_from_jwt(token).key
    except Exception as e:  # network error, unknown kid, malformed JWKS
        raise OIDCError(f"could not fetch JWKS signing key: {e}") from e


def verify_oidc_token(
    token: str,
    *,
    config: OIDCConfig | None = None,
    signing_key: Any = None,
) -> VerifiedPrincipal:
    """Verify an OIDC ID token and return its :class:`VerifiedPrincipal`.

    Args:
        token: the raw compact JWT (the ``id_token`` from the IdP).
        config: resolved :class:`OIDCConfig`; defaults to :func:`load_oidc_config`.
        signing_key: optional verification key OR a ``PyJWKClient``-like
            resolver. When provided, NO network call is made — this is the test
            seam (mint a token with a local RSA key, inject the public key).
            When ``None``, a :class:`jwt.PyJWKClient` is built from
            ``config.jwks_uri`` and the key is resolved by the token's ``kid``.

    Raises:
        OIDCError: on a missing/invalid token, missing config (issuer/audience),
            an unresolvable ``kid``, a disallowed algorithm, a bad signature, an
            expired token, an audience/issuer mismatch, or any missing required
            claim. NEVER returns on failure — there is no fail-open path.
    """
    cfg = config if config is not None else load_oidc_config()

    if not isinstance(token, str) or not token.strip():
        raise OIDCError("empty or non-string token")
    if not cfg.issuer:
        raise OIDCError("OIDC issuer is not configured")
    if not cfg.audience:
        raise OIDCError("OIDC audience is not configured")

    algorithms = _safe_algorithms(cfg)
    jwt_mod = _require_pyjwt()

    key = _resolve_signing_key(
        jwt_mod, token, signing_key=signing_key, config=cfg
    )

    try:
        claims = jwt_mod.decode(
            token,
            key,
            algorithms=algorithms,
            audience=cfg.audience,
            issuer=cfg.issuer,
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )
    except jwt_mod.InvalidTokenError as e:
        # Covers expiry, aud/iss mismatch, bad signature, disallowed alg
        # (incl. the HS256-with-public-key alg-confusion attempt, which PyJWT
        # rejects because HS256 isn't in `algorithms`), and missing required
        # claims. All collapse to one opaque OIDCError — no detail that helps
        # an attacker distinguish failure modes.
        raise OIDCError(f"token verification failed: {e}") from e
    except Exception as e:  # defensive: never leak a non-OIDCError to callers
        raise OIDCError(f"token verification failed: {e}") from e

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        # `require` already enforces presence, but a non-string/empty sub would
        # yield a bogus `user:` principal — reject explicitly.
        raise OIDCError("token 'sub' claim is missing or invalid")

    return VerifiedPrincipal(
        sub=sub,
        issuer=cfg.issuer,
        audience=cfg.audience,
        claims=claims,
    )


__all__ = [
    "OIDCError",
    "OIDCConfig",
    "VerifiedPrincipal",
    "DEFAULT_ALGORITHMS",
    "oidc_enabled",
    "load_oidc_config",
    "verify_oidc_token",
]
