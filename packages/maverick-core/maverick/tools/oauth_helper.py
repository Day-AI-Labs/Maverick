"""Generic OAuth helper (roadmap: 2027 H2 ecosystem).

Every connector that wants OAuth today reinvents the same three steps:
build the authorize URL, exchange the code, refresh the token. The `oidc`
tool covers the OpenID flavor; this is the **plain OAuth2** generalisation
for any provider (GitHub, Slack, HubSpot, Google, ...): authorization-code
with PKCE by default, plus refresh — provider-agnostic, endpoints supplied
by the caller (or by a named preset).

Secrets discipline: token responses are summarised (token *type*, expiry,
scope, and a fingerprint), never echoed — an access token printed into a
model context is a leak. The caller is told where the full token went
(``MAVERICK_OAUTH_OUT`` env-named file, 0600) so a human wires it into the
right connector config without the model ever seeing it.

ops:
  - authorize_url(authorize_url, client_id, redirect_uri[, scope, state])
      — returns the URL to open + the PKCE verifier to keep.
  - exchange(token_url, client_id, code, redirect_uri[, verifier,
      client_secret]) — code -> tokens (summarised; full set written to the
      out-file when configured).
  - refresh(token_url, client_id, refresh_token[, client_secret]) — rotate.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


def _post_form(url: str, data: dict[str, str]) -> dict:
    import httpx
    r = httpx.post(url, data=data,
                   headers={"Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    return r.json()


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def _persist_tokens(payload: dict) -> str | None:
    """Write the full token response to the operator-named out-file (0600).

    Returns the path written, or None when MAVERICK_OAUTH_OUT is unset (then
    only the summary exists and the caller must re-run with it set to capture
    the secret material)."""
    out = os.environ.get("MAVERICK_OAUTH_OUT", "").strip()
    if not out:
        return None
    from pathlib import Path
    p = Path(out).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return str(p)


def _summarise(resp: dict) -> list[str]:
    lines = []
    access = str(resp.get("access_token") or "")
    if access:
        lines.append(f"access_token: <redacted> (sha256:{_fingerprint(access)}, "
                     f"{len(access)} chars)")
    if resp.get("token_type"):
        lines.append(f"token_type: {resp['token_type']}")
    if resp.get("expires_in") is not None:
        lines.append(f"expires_in: {resp['expires_in']}s")
    if resp.get("scope"):
        lines.append(f"scope: {resp['scope']}")
    if resp.get("refresh_token"):
        lines.append("refresh_token: <redacted> (present)")
    return lines


def _authorize_url(args: dict[str, Any]) -> str:
    for req in ("authorize_url", "client_id", "redirect_uri"):
        if not args.get(req):
            return f"ERROR: {req} is required"
    from urllib.parse import urlencode

    from ..mcp_oauth import generate_pkce
    verifier, challenge = generate_pkce()
    params = {
        "response_type": "code",
        "client_id": str(args["client_id"]),
        "redirect_uri": str(args["redirect_uri"]),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if args.get("scope"):
        params["scope"] = str(args["scope"])
    if args.get("state"):
        params["state"] = str(args["state"])
    url = f"{args['authorize_url']}?{urlencode(params)}"
    return (f"open: {url}\n"
            f"pkce_verifier: {verifier}\n"
            "(keep the verifier; pass it to op=exchange as 'verifier')")


def _exchange(args: dict[str, Any]) -> str:
    for req in ("token_url", "client_id", "code", "redirect_uri"):
        if not args.get(req):
            return f"ERROR: {req} is required"
    data = {
        "grant_type": "authorization_code",
        "client_id": str(args["client_id"]),
        "code": str(args["code"]),
        "redirect_uri": str(args["redirect_uri"]),
    }
    if args.get("verifier"):
        data["code_verifier"] = str(args["verifier"])
    if args.get("client_secret"):
        data["client_secret"] = str(args["client_secret"])
    try:
        resp = _post_form(str(args["token_url"]), data)
    except Exception as e:
        return f"ERROR: token exchange failed: {e}"
    if not resp.get("access_token"):
        return f"ERROR: no access_token in response: {json.dumps(resp)[:200]}"
    lines = _summarise(resp)
    saved = _persist_tokens(resp)
    lines.append(f"full tokens written to: {saved}" if saved else
                 "set MAVERICK_OAUTH_OUT=<path> to capture the full tokens to a 0600 file")
    return "\n".join(lines)


def _refresh(args: dict[str, Any]) -> str:
    for req in ("token_url", "client_id", "refresh_token"):
        if not args.get(req):
            return f"ERROR: {req} is required"
    data = {
        "grant_type": "refresh_token",
        "client_id": str(args["client_id"]),
        "refresh_token": str(args["refresh_token"]),
    }
    if args.get("client_secret"):
        data["client_secret"] = str(args["client_secret"])
    try:
        resp = _post_form(str(args["token_url"]), data)
    except Exception as e:
        return f"ERROR: token refresh failed: {e}"
    if not resp.get("access_token"):
        return f"ERROR: no access_token in response: {json.dumps(resp)[:200]}"
    lines = _summarise(resp)
    saved = _persist_tokens(resp)
    if saved:
        lines.append(f"full tokens written to: {saved}")
    return "\n".join(lines)


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if op == "authorize_url":
        return _authorize_url(args)
    if op == "exchange":
        return _exchange(args)
    if op == "refresh":
        return _refresh(args)
    return f"ERROR: unknown op {op!r} (expected authorize_url/exchange/refresh)"


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["authorize_url", "exchange", "refresh"]},
        "authorize_url": {"type": "string"},
        "token_url": {"type": "string"},
        "client_id": {"type": "string"},
        "client_secret": {"type": "string", "description": "confidential clients only"},
        "redirect_uri": {"type": "string"},
        "scope": {"type": "string"},
        "state": {"type": "string"},
        "code": {"type": "string", "description": "authorization code (exchange)"},
        "verifier": {"type": "string", "description": "PKCE verifier from authorize_url"},
        "refresh_token": {"type": "string"},
    },
    "required": ["op"],
}


def oauth_helper() -> Tool:
    return Tool(
        name="oauth_helper",
        description=(
            "Generic OAuth2 flow for any provider. op=authorize_url builds the "
            "consent URL (PKCE S256) and returns the verifier to keep; "
            "op=exchange swaps the code for tokens; op=refresh rotates. Token "
            "responses are summarised with a fingerprint, never echoed; set "
            "MAVERICK_OAUTH_OUT to write the full tokens to a 0600 file."
        ),
        input_schema=_SCHEMA,
        fn=_run,
    )
