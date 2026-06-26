"""SAML 2.0 SP browser SSO (via pysaml2).

A second SSO front-end alongside OIDC for enterprises that mandate SAML. An IdP
(Okta, Entra/Azure AD, OneLogin, ADFS) POSTs a **signed assertion** to the ACS;
pysaml2 verifies the XML signature (we never hand-roll XML-dsig), and we mint the
SAME ``mvk_session`` cookie the OIDC browser login issues -- so a SAML user flows
through ``require_principal`` / RBAC exactly like an OIDC one, with no downstream
changes. The principal is ``user:<NameID>``.

OFF by default: with no ``[auth.saml]`` config every route 404s, so mounting the
router is inert until an operator opts in. The signed session reuses the
browser-login secret (``[auth.oidc] session_secret``), so that must be set too.

pysaml2 is the optional ``[saml]`` extra, imported lazily; the routes 503 with a
clear hint if it's absent. Endpoints (mounted under the dashboard app):

  GET  /saml/metadata  -> SP metadata XML (hand this to the IdP)
  GET  /saml/login     -> redirect to the IdP SSO (AuthnRequest)
  POST /saml/acs       -> consume + verify the SAMLResponse, set session, redirect

NOTE: untested against a live IdP in this build -- the pysaml2 calls
(``_client``/metadata/redirect/parse) are isolated so the surrounding routing,
attribute mapping and session minting are unit-tested with the client mocked;
certify a real Okta/Entra round-trip before relying on it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

log = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

_SESSION_TTL = 8 * 60 * 60  # 8h, matching the OIDC browser session
_MAX_ACS_BODY_BYTES = 1024 * 1024
_MAX_SAML_RESPONSE_BYTES = 768 * 1024


class SamlUnavailable(RuntimeError):
    """SAML was requested but pysaml2 (the [saml] extra) isn't installed."""


@dataclass(frozen=True)
class SamlConfig:
    sp_entity_id: str = ""
    acs_url: str = ""
    idp_metadata_url: str = ""
    idp_metadata_file: str = ""
    sp_cert_file: str = ""
    sp_key_file: str = ""
    want_assertions_signed: bool = True
    name_attr: str = ""  # attribute to prefer for display, optional
    default_relay_state: str = "/"


def _content_length(headers: Mapping[str, str]) -> int | None:
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


async def _cache_limited_body(request: Request, *, limit: int) -> bool:
    """Cache the request body only if it fits within ``limit`` bytes.

    The SAML ACS endpoint is intentionally unauthenticated because IdPs POST to
    it before a browser session exists.  Avoid ``request.form()`` until this has
    bounded the body: Starlette/FastAPI form parsing buffers the full request.
    """
    length = _content_length(request.headers)
    if length is not None and length > limit:
        return False
    size = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return False
        chunks.append(chunk)
    # Starlette's Request.stream()/body()/form() use this cache when present.
    request._body = b"".join(chunks)  # noqa: SLF001 -- deliberate pre-parse cap
    return True


def _form_value_too_large(value: str, *, limit: int) -> bool:
    return len(value.encode("utf-8")) > limit


def _auth_saml_cfg() -> dict[str, Any]:
    try:
        from maverick.config import load_config

        cfg = ((load_config() or {}).get("auth") or {}).get("saml") or {}
    except Exception:  # pragma: no cover -- config never blocks a request
        return {}
    return cfg if isinstance(cfg, dict) else {}


def load_saml_config() -> SamlConfig:
    c = _auth_saml_cfg()
    return SamlConfig(
        sp_entity_id=str(c.get("sp_entity_id") or "").strip(),
        acs_url=str(c.get("acs_url") or "").strip(),
        idp_metadata_url=str(c.get("idp_metadata_url") or "").strip(),
        idp_metadata_file=str(c.get("idp_metadata_file") or "").strip(),
        sp_cert_file=str(c.get("sp_cert_file") or "").strip(),
        sp_key_file=str(c.get("sp_key_file") or "").strip(),
        want_assertions_signed=bool(c.get("want_assertions_signed", True)),
        name_attr=str(c.get("name_attr") or "").strip(),
        default_relay_state=str(c.get("default_relay_state") or "/").strip() or "/",
    )


def saml_enabled(cfg: SamlConfig | None = None) -> bool:
    """Configured = an SP entity id + ACS URL + an IdP metadata source. With any
    missing the surface 404s (inert)."""
    cfg = cfg or load_saml_config()
    return bool(
        cfg.sp_entity_id and cfg.acs_url and (cfg.idp_metadata_url or cfg.idp_metadata_file)
    )


def _session_secret() -> str:
    """The browser-login session secret (shared with OIDC), so the cookie we mint
    is accepted by the same verifier. Empty -> SAML can't issue a session."""
    try:
        from maverick.oidc import load_oidc_config

        return str(getattr(load_oidc_config(), "session_secret", "") or "")
    except Exception:  # pragma: no cover
        return ""


# --- pysaml2 isolation (untestable here; mocked in tests) -------------------


def _pysaml2_config(cfg: SamlConfig) -> dict:
    from saml2 import BINDING_HTTP_POST, BINDING_HTTP_REDIRECT  # type: ignore

    metadata: dict = {}
    if cfg.idp_metadata_url:
        metadata["remote"] = [{"url": cfg.idp_metadata_url}]
    if cfg.idp_metadata_file:
        metadata.setdefault("local", []).append(cfg.idp_metadata_file)
    conf: dict = {
        "entityid": cfg.sp_entity_id,
        "service": {
            "sp": {
                "endpoints": {
                    "assertion_consumer_service": [(cfg.acs_url, BINDING_HTTP_POST)],
                },
                "allow_unsolicited": True,
                "authn_requests_signed": bool(cfg.sp_key_file),
                "want_assertions_signed": cfg.want_assertions_signed,
                "want_response_signed": False,
            }
        },
        "metadata": metadata,
        "allow_unknown_attributes": True,
    }
    if cfg.sp_cert_file and cfg.sp_key_file:
        conf["cert_file"] = cfg.sp_cert_file
        conf["key_file"] = cfg.sp_key_file
    # bindings imported only to fail fast if pysaml2 is the wrong shape
    _ = (BINDING_HTTP_POST, BINDING_HTTP_REDIRECT)
    return conf


def _client(cfg: SamlConfig | None = None):  # pragma: no cover -- needs pysaml2
    cfg = cfg or load_saml_config()
    try:
        from saml2.client import Saml2Client  # type: ignore
        from saml2.config import Config  # type: ignore
    except ImportError as e:
        raise SamlUnavailable("SAML SSO needs pysaml2 (pip install 'maverick-agent[saml]')") from e
    conf = Config()
    conf.load(_pysaml2_config(cfg))
    return Saml2Client(config=conf)


def sp_metadata_xml(client=None, cfg: SamlConfig | None = None) -> str:  # pragma: no cover
    from saml2.metadata import create_metadata_string  # type: ignore

    client = client or _client(cfg)
    return create_metadata_string(None, config=client.config).decode("utf-8")


def login_redirect_url(
    client=None, cfg: SamlConfig | None = None, *, relay_state: str = "/"
) -> str:  # pragma: no cover
    from saml2 import BINDING_HTTP_REDIRECT  # type: ignore

    client = client or _client(cfg)
    _reqid, info = client.prepare_for_authenticate(
        relay_state=relay_state, binding=BINDING_HTTP_REDIRECT
    )
    return dict(info["headers"]).get("Location", "")


def verify_acs_response(saml_response: str) -> SamlIdentity:  # pragma: no cover
    """Verify a posted SAMLResponse (pysaml2 checks the XML signature) and return
    the identity. Isolated so the ACS route logic is testable with this mocked."""
    from saml2 import BINDING_HTTP_POST  # type: ignore

    client = _client()
    authn = client.parse_authn_request_response(saml_response, BINDING_HTTP_POST)
    return extract_identity(authn)


# --- mapping + session (testable) -------------------------------------------


@dataclass(frozen=True)
class SamlIdentity:
    name_id: str
    attributes: dict[str, list] = field(default_factory=dict)

    @property
    def principal(self) -> str:
        return f"user:{self.name_id}"


def extract_identity(authn_response) -> SamlIdentity:
    """Pull the NameID + attributes out of a *verified* pysaml2 AuthnResponse.

    Pure mapping (no crypto) -- pysaml2 already verified the signature before
    this is called, so a None/unsigned response must never reach here."""
    if authn_response is None:
        raise SamlUnavailable("SAML response did not verify")
    name_id = ""
    nid = getattr(authn_response, "name_id", None)
    if nid is not None:
        name_id = str(getattr(nid, "text", "") or "").strip()
    if not name_id:
        try:
            subj = authn_response.get_subject()
            name_id = str(getattr(subj, "text", "") or "").strip()
        except Exception:  # pragma: no cover -- response shape varies
            name_id = ""
    if not name_id:
        raise SamlUnavailable("SAML assertion carried no NameID")
    try:
        attrs = authn_response.get_identity() or {}
    except Exception:  # pragma: no cover
        attrs = {}
    return SamlIdentity(name_id=name_id, attributes=dict(attrs))


def mint_session_cookie(name_id: str, *, secret: str | None = None) -> str:
    """Sign an ``mvk_session`` value for ``user:<name_id>`` -- the SAME cookie the
    OIDC browser login issues, so it verifies through the shared session path."""
    from maverick.web_session import sign_session

    secret = secret if secret is not None else _session_secret()
    if not secret:
        raise SamlUnavailable(
            "SAML needs the browser-login session secret ([auth.oidc] "
            "session_secret) to issue a session")
    now = int(time.time())
    return sign_session({"sub": name_id, "iat": now, "exp": now + _SESSION_TTL},
                        secret)


def _safe_relay_state(value: str | None, default: str) -> str:
    """Only allow same-site relative paths as the post-login redirect target."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return default
    return value


# Attribute names IdPs commonly carry the stable email / UPN under. SCIM
# deprovision revokes by externalId/userName/email/id, so recording the SAML
# NameID against these lets ``subject_directory.subs_for`` reach a session whose
# sub is a persistent/transient NameID that matches no SCIM attribute.
_EMAIL_UPN_ATTRS = (
    "email", "mail", "emailaddress", "emailAddress",
    "upn", "userPrincipalName", "userprincipalname",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn",
)


def _record_session_subject(identity: SamlIdentity) -> None:
    """Map the SAML NameID (the session sub) to the user's stable email/UPN
    identifiers so a later SCIM deprovision can revoke this live session even
    when the IdP uses a persistent/transient NameID (the recommended format),
    which appears in no SCIM attribute. Best-effort: never blocks the login."""
    try:
        from .subject_directory import record_login

        ids: list[str] = [identity.name_id]
        attrs = identity.attributes or {}
        for key in _EMAIL_UPN_ATTRS:
            for val in attrs.get(key) or ():
                if isinstance(val, str):
                    ids.append(val)
        record_login(identity.name_id, ids)
    except Exception:  # pragma: no cover -- directory never blocks login
        return


# --- routes -----------------------------------------------------------------


def _disabled() -> JSONResponse | None:
    return (
        None
        if saml_enabled()
        else JSONResponse({"detail": "SAML SSO is not enabled"}, status_code=404)
    )


@router.get("/saml/metadata")
async def saml_metadata(request: Request):
    if (off := _disabled()) is not None:
        return off
    try:
        xml = sp_metadata_xml()
    except SamlUnavailable as e:
        return JSONResponse({"detail": str(e)}, status_code=503)
    from fastapi.responses import Response

    return Response(content=xml, media_type="application/samlmetadata+xml")


@router.get("/saml/login")
async def saml_login(request: Request):
    if (off := _disabled()) is not None:
        return off
    cfg = load_saml_config()
    relay = _safe_relay_state(request.query_params.get("return_to"), cfg.default_relay_state)
    try:
        url = login_redirect_url(cfg=cfg, relay_state=relay)
    except SamlUnavailable as e:
        return JSONResponse({"detail": str(e)}, status_code=503)
    if not url:
        return JSONResponse({"detail": "could not build SAML AuthnRequest"}, status_code=502)
    return RedirectResponse(url, status_code=303)


@router.post("/saml/acs")
async def saml_acs(request: Request):
    if (off := _disabled()) is not None:
        return off
    if not await _cache_limited_body(request, limit=_MAX_ACS_BODY_BYTES):
        return JSONResponse({"detail": "SAML ACS request too large"}, status_code=413)
    form = await request.form()
    saml_response = str(form.get("SAMLResponse") or "")
    if _form_value_too_large(saml_response, limit=_MAX_SAML_RESPONSE_BYTES):
        return JSONResponse({"detail": "SAMLResponse too large"}, status_code=413)
    relay = _safe_relay_state(
        str(form.get("RelayState") or ""), load_saml_config().default_relay_state
    )
    if not saml_response:
        return JSONResponse({"detail": "missing SAMLResponse"}, status_code=400)
    try:
        identity = verify_acs_response(saml_response)
        cookie = mint_session_cookie(identity.name_id)
    except SamlUnavailable as e:
        return JSONResponse({"detail": str(e)}, status_code=503)
    except Exception:  # noqa: BLE001 -- never leak why verification failed
        log.warning("SAML ACS: assertion verification failed")
        return JSONResponse({"detail": "SAML assertion did not verify"}, status_code=401)
    # Record the NameID (the session sub) so SCIM deprovision can revoke this
    # live session even for a persistent/transient NameID that maps to no SCIM
    # attribute. Mirrors the OIDC callback's record_login.
    _record_session_subject(identity)
    # Reuse the OIDC login cookie hardening so SAML/OIDC sessions are identical.
    from .oidc_login import SESSION_COOKIE, _is_loopback_request, _set_cookie

    response = RedirectResponse(relay, status_code=303)
    _set_cookie(
        response,
        SESSION_COOKIE,
        cookie,
        max_age=_SESSION_TTL,
        secure=not _is_loopback_request(request),
    )
    return response


__all__ = [
    "router",
    "saml_enabled",
    "load_saml_config",
    "SamlConfig",
    "SamlIdentity",
    "SamlUnavailable",
    "extract_identity",
    "mint_session_cookie",
]
