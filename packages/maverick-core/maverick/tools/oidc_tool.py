"""Generic OIDC tool: build an authorization URL + exchange a code for tokens.

A thin OpenID Connect / OAuth 2.1 *authorization-code* client (the user-redirect
flow, complementing ``mcp_oauth``'s machine-to-machine client_credentials):

  - ``authorize``: construct the authorization-endpoint redirect URL (client_id,
    redirect_uri, scope, state). Pure — no network.
  - ``exchange``: POST the authorization code to the token endpoint and return
    the token response.

The token POST is injectable (``fetch=``) so ``exchange_code`` unit-tests against
a mock token endpoint with no network (same pattern as ``mcp_oauth``). Token URLs
must be https. Optionally decodes an ``id_token`` claim set when ``pyjwt`` is
installed (``pip install maverick-agent[oidc]``).
"""
from __future__ import annotations

from urllib.parse import urlencode, urlparse

from . import Tool

_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["authorize", "exchange"]},
        "authorize_url": {"type": "string"},
        "token_url": {"type": "string"},
        "client_id": {"type": "string"},
        "client_secret": {"type": "string"},
        "redirect_uri": {"type": "string"},
        "scope": {"type": "string", "description": "default 'openid profile email'"},
        "state": {"type": "string"},
        "code": {"type": "string", "description": "authorization code (exchange op)"},
    },
    "required": ["op"],
}


def build_authorize_url(authorize_url: str, client_id: str, redirect_uri: str, *,
                        scope: str = "openid profile email", state: str = "",
                        response_type: str = "code") -> str:
    """Construct the OIDC authorization redirect URL. Pure (no network)."""
    if not authorize_url or not client_id or not redirect_uri:
        raise ValueError("authorize needs authorize_url, client_id, redirect_uri")
    params = {
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
    }
    if state:
        params["state"] = state
    sep = "&" if urlparse(authorize_url).query else "?"
    return f"{authorize_url}{sep}{urlencode(params)}"


def _default_fetch(token_url: str, data: dict) -> dict:
    import json
    import urllib.request
    body = urlencode(data).encode()
    req = urllib.request.Request(
        token_url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 -- https-checked
        return json.loads(r.read(200_000).decode("utf-8"))


def exchange_code(token_url: str, client_id: str, code: str, redirect_uri: str, *,
                  client_secret: str = "", fetch=None) -> dict:
    """Exchange an authorization code for tokens via the token endpoint.

    ``fetch(token_url, data) -> dict`` is injectable for tests. Raises
    ``ValueError`` on bad input or a token endpoint that returns no access_token.
    """
    if not token_url.startswith("https://"):
        raise ValueError(f"token_url must be https://, got {token_url!r}")
    if not client_id or not code or not redirect_uri:
        raise ValueError("exchange needs client_id, code, redirect_uri")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    if client_secret:
        data["client_secret"] = client_secret
    resp = (fetch or _default_fetch)(token_url, data)
    if not isinstance(resp, dict) or not resp.get("access_token"):
        raise ValueError("token endpoint did not return an access_token")
    return resp


def _summarise_tokens(resp: dict) -> str:
    keys = [k for k in ("access_token", "id_token", "refresh_token",
                        "token_type", "expires_in", "scope") if k in resp]
    out = [f"token exchange ok; fields: {', '.join(keys)}"]
    if resp.get("id_token"):
        try:
            import jwt
            claims = jwt.decode(resp["id_token"], options={"verify_signature": False})
            who = claims.get("email") or claims.get("sub") or "?"
            out.append(f"id_token subject: {who}")
        except ImportError:
            out.append("(install maverick-agent[oidc] to decode the id_token)")
        except Exception:  # pragma: no cover -- malformed token
            out.append("(id_token present but could not be decoded)")
    return "\n".join(out)


def _run(args: dict) -> str:
    op = args.get("op")
    try:
        if op == "authorize":
            return build_authorize_url(
                args.get("authorize_url") or "", args.get("client_id") or "",
                args.get("redirect_uri") or "",
                scope=args.get("scope") or "openid profile email",
                state=args.get("state") or "")
        if op == "exchange":
            resp = exchange_code(
                args.get("token_url") or "", args.get("client_id") or "",
                args.get("code") or "", args.get("redirect_uri") or "",
                client_secret=args.get("client_secret") or "")
            return _summarise_tokens(resp)
    except ValueError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: token request failed: {type(e).__name__}: {e}"
    return f"ERROR: unknown op {op!r}"


def oidc_tool() -> Tool:
    return Tool(
        name="oidc",
        description=(
            "Generic OIDC / OAuth2 authorization-code client. ops: authorize "
            "(build the redirect URL from authorize_url, client_id, redirect_uri, "
            "scope, state), exchange (swap a code for tokens at token_url). Token "
            "URL must be https."
        ),
        input_schema=_SCHEMA,
        fn=_run,
    )


__all__ = ["oidc_tool", "build_authorize_url", "exchange_code"]
