"""Generic authenticated-REST connector factory.

Most enterprise SaaS exposes a token-authed JSON REST API with the same shape:
a base URL, a bearer/basic/custom-header token, GET to read, POST/PUT/PATCH/
DELETE to write. ``make_rest_tool`` turns that shape into a Maverick ``Tool``
so the long tail of connectors is a one-line spec instead of a hand-written
module — while keeping the house rules: explicit-env auth (no ambient creds),
``confirm=true`` gating on every write, ``ERROR:``-prefixed failures, and a
lazy ``httpx`` import.

The agent supplies the API ``path`` (the description carries the base URL +
auth env + a couple of example paths), so one factory covers every endpoint of
a service without hard-coding entities.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any
from urllib.parse import unquote, urlsplit

from . import Tool, as_bool

_WRITE_OPS = {"post", "put", "patch", "delete"}


def _env_config(name: str, base_url_env: str, token_env: str) -> tuple[str, str]:
    """Resolve (base_url, token) from env or raise a loud, consistent error.
    Shared by the REST and GraphQL factories so they can't drift."""
    base = os.environ.get(base_url_env, "").strip().rstrip("/")
    tok = os.environ.get(token_env, "").strip()
    if not base or not tok:
        raise RuntimeError(f"{name} requires {base_url_env} + {token_env}.")
    return base, tok


def _build_auth_headers(
    tok: str, *, basic: bool, token_header: str, scheme: str,
    extra_headers_env: dict[str, str] | None,
) -> dict[str, str]:
    """Auth + content headers for a connector. Handles bearer/custom-scheme,
    HTTP basic, and APIM-style extra-header creds -- shared by REST and GraphQL
    so a GraphQL service needing basic/extra-header auth works like REST."""
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if basic:
        raw = tok if ":" in tok else f"{tok}:x"
        h["Authorization"] = "Basic " + base64.b64encode(raw.encode()).decode("ascii")
    else:
        h[token_header] = f"{scheme} {tok}".strip()
    for hdr, env_name in (extra_headers_env or {}).items():
        val = os.environ.get(env_name, "").strip()
        if val:
            h[hdr] = val
    return h

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["get", "post", "put", "patch", "delete"]},
        "path": {"type": "string", "description": "API path beginning with /..."},
        "params": {"type": "object", "description": "query params (get)."},
        "body": {"type": "object", "description": "JSON body (write ops)."},
        "confirm": {"type": "boolean", "description": "required for write ops."},
    },
    "required": ["op", "path"],
}

_READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["get"], "description": "read-only: get."},
        "path": {"type": "string", "description": "API path beginning with /..."},
        "params": {"type": "object", "description": "query params."},
    },
    "required": ["path"],
}


def _rest_validate(
    args: dict[str, Any],
    *,
    name: str,
    read_only: bool,
    read_prefixes: tuple[str, ...],
    read_path_allowed,
    norm,
) -> tuple[str, str] | str:
    """Validate op/path/confirm. Returns ``(op, path)`` or an ``ERROR/DRY RUN`` string."""
    op = (args.get("op") or ("get" if read_only else "")).strip().lower()
    if read_only and op != "get":
        return f"ERROR: {name} is read-only -- only GET is permitted from this seat."
    if op not in ("get", "post", "put", "patch", "delete"):
        return f"ERROR: op must be get/post/put/patch/delete (got {op!r})"
    path = (args.get("path") or "").strip()
    if not path:
        return "ERROR: path is required"
    if read_only and not read_path_allowed(path):
        allowed = ", ".join(read_prefixes) or "(none)"
        return f"ERROR: {name} read path is not allowed. Allowed prefixes: {allowed}"
    try:
        import httpx  # noqa: F401
    except ImportError:
        return "ERROR: httpx not installed. Run: pip install 'maverick-agent[issue-trackers]'"
    if op in _WRITE_OPS and not as_bool(args.get("confirm")):
        return f"DRY RUN: would {op.upper()} {norm(path)}. Re-run with confirm=true."
    return op, path


def _rest_execute(
    op: str,
    path: str,
    args: dict[str, Any],
    *,
    name: str,
    config,
    headers,
    norm,
) -> str:
    """Perform the authenticated REST request and render the response."""
    params = args.get("params") if isinstance(args.get("params"), dict) else None
    body = args.get("body") if isinstance(args.get("body"), dict) else None
    try:
        base, tok = config()
        url = f"{base}{norm(path)}"
        # Enterprise mode: a connector POSTs agent-supplied content to a
        # third-party SaaS host -- hold it to the egress boundary too.
        from ..enterprise import enterprise_egress_denial
        deny = enterprise_egress_denial(url, tool=name)
        if deny:
            return f"ERROR: {deny}"
        # Route through the SSRF-safe client: resolve the host ONCE and pin the
        # connection to that validated public IP, so DNS-rebinding can't point
        # the configured connector host at an internal/metadata address
        # (169.254.169.254, 127.0.0.1) after the egress check above. The bearer
        # token rides this request, so an unpinned fetch could exfil it. Redirects
        # stay off (safe_client default) -- only ``url`` passed the gate. On-prem
        # connectors opt in via MAVERICK_FETCH_ALLOW_PRIVATE=1.
        from ._ssrf import BlockedHost, safe_client
        try:
            with safe_client(url, timeout=30.0) as client:
                r = client.request(op.upper(), url, headers=headers(tok),
                                   params=params or None, json=body)
        except BlockedHost as e:
            return f"ERROR: blocked host (SSRF guard): {e}"
        try:
            data = r.json()
        except ValueError:
            data = (r.text or "")[:1500]
        if r.status_code >= 400:
            return f"ERROR: {op} ({r.status_code}): {data}"
        return json.dumps(data, default=str)[:4000]
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {name} request failed: {type(e).__name__}: {e}"


def make_rest_tool(
    *,
    name: str,
    base_url_env: str,
    token_env: str,
    description: str,
    token_header: str = "Authorization",
    scheme: str = "Bearer",
    basic: bool = False,
    read_only: bool = False,
    allowed_read_paths: tuple[str, ...] | None = None,
    extra_headers_env: dict[str, str] | None = None,
) -> Tool:
    """Build a thin authenticated-REST ``Tool``.

    Auth modes:
      - ``basic=True``  -> ``Authorization: Basic b64(token)`` (token is
        ``user:pass``; a bare token is treated as ``token:x``, the API-key
        convention used by Freshdesk / Greenhouse / Lever / BambooHR).
      - else ``{token_header}: {scheme} {token}`` (``scheme=""`` sends the raw
        token, e.g. Tableau's ``X-Tableau-Auth``).

    ``extra_headers_env`` maps additional header names to env-var names for
    APIs that need a second credential alongside the token (Azure-APIM-style
    gateways, e.g. CCH Axcess's ``Ocp-Apim-Subscription-Key``). A header is
    sent only when its env var is set; required ones are listed in the
    connector's description so a missing key fails loudly at the API.

    ``read_only=True`` exposes GET only -- a low-risk read seat (write ops are
    refused), so a read-only agent/pack can pull data without a write-capable
    tool. The connector's writes are simply unreachable from this seat.

    ``allowed_read_paths`` optionally narrows a read-only connector to known-safe
    API resource prefixes. This is intended for credentialed finance APIs where
    GET-only is not, by itself, an adequate data-access boundary.
    """

    def _config() -> tuple[str, str]:
        return _env_config(name, base_url_env, token_env)

    def _headers(tok: str) -> dict[str, str]:
        return _build_auth_headers(
            tok, basic=basic, token_header=token_header, scheme=scheme,
            extra_headers_env=extra_headers_env,
        )

    def _norm(path: str) -> str:
        p = path.strip()
        return p if p.startswith("/") else "/" + p

    read_prefixes = tuple(_norm(p) for p in (allowed_read_paths or ()))

    def _request_path(path: str) -> str | None:
        # Keep endpoint authorization independent from query strings. Agents may
        # pass query params separately via ``params``; embedding a query in path
        # must not help bypass or broaden endpoint checks. Percent-decode before
        # checking segments so encoded dot-segment traversal cannot pass the
        # allowlist and be normalized by the HTTP stack or upstream service.
        parsed = urlsplit(_norm(path))
        request_path = unquote(parsed.path or "/")
        if any(segment in (".", "..") for segment in request_path.split("/")):
            return None
        return request_path

    def _read_path_allowed(path: str) -> bool:
        if not read_prefixes:
            return True
        request_path = _request_path(path)
        if request_path is None:
            return False
        return any(
            request_path == prefix or request_path.startswith(f"{prefix}/")
            for prefix in read_prefixes
        )

    def _run(args: dict[str, Any]) -> str:
        validated = _rest_validate(
            args,
            name=name,
            read_only=read_only,
            read_prefixes=read_prefixes,
            read_path_allowed=_read_path_allowed,
            norm=_norm,
        )
        if isinstance(validated, str):
            return validated
        op, path = validated
        return _rest_execute(
            op, path, args,
            name=name,
            config=_config,
            headers=_headers,
            norm=_norm,
        )

    return Tool(name=name, description=description,
                input_schema=_READ_SCHEMA if read_only else _SCHEMA, fn=_run)


def _is_gql_name_char(ch: str) -> bool:
    return ch == "_" or ch.isalnum()


def _skip_gql_ignored(text: str, pos: int) -> int:
    while pos < len(text):
        ch = text[pos]
        if ch.isspace() or ch == ",":
            pos += 1
            continue
        if ch == "#":
            newline = text.find("\n", pos)
            if newline == -1:
                return len(text)
            pos = newline + 1
            continue
        break
    return pos


def _gql_word_at(text: str, pos: int, word: str) -> bool:
    end = pos + len(word)
    return (
        text[pos:end].lower() == word
        and (pos == 0 or not _is_gql_name_char(text[pos - 1]))
        and (end == len(text) or not _is_gql_name_char(text[end]))
    )


def _skip_gql_string(text: str, pos: int) -> int:
    if text.startswith('"""', pos):
        end = text.find('"""', pos + 3)
        return len(text) if end == -1 else end + 3

    pos += 1
    while pos < len(text):
        ch = text[pos]
        if ch == "\\":
            pos += 2
        elif ch == '"':
            return pos + 1
        else:
            pos += 1
    return pos


def _skip_gql_braced(text: str, pos: int) -> int:
    depth = 0
    while pos < len(text):
        pos = _skip_gql_ignored(text, pos)
        if pos >= len(text):
            return pos
        ch = text[pos]
        if ch == '"':
            pos = _skip_gql_string(text, pos)
        elif ch == "{":
            depth += 1
            pos += 1
        elif ch == "}":
            depth -= 1
            pos += 1
            if depth <= 0:
                return pos
        else:
            pos += 1
    return pos


def _skip_gql_definition(text: str, pos: int) -> int:
    paren_depth = 0
    while pos < len(text):
        pos = _skip_gql_ignored(text, pos)
        if pos >= len(text):
            return pos
        ch = text[pos]
        if ch == '"':
            pos = _skip_gql_string(text, pos)
            continue
        if ch == "(":
            paren_depth += 1
        elif ch == ")" and paren_depth:
            paren_depth -= 1
        elif ch == "{":
            if paren_depth == 0:
                return _skip_gql_braced(text, pos)
            pos = _skip_gql_braced(text, pos)
            continue
        pos += 1
    return pos


def _graphql_has_mutation(text: str) -> bool:
    """Return whether a GraphQL document contains a mutation operation."""
    pos = 0
    while True:
        pos = _skip_gql_ignored(text, pos)
        while pos < len(text) and text[pos] == "(":
            pos = _skip_gql_ignored(text, pos + 1)
        if pos >= len(text):
            return False
        if _gql_word_at(text, pos, "mutation"):
            return True
        if _gql_word_at(text, pos, "query") or _gql_word_at(text, pos, "subscription"):
            pos = _skip_gql_definition(text, pos)
            continue
        if _gql_word_at(text, pos, "fragment") or text[pos] == "{":
            pos = _skip_gql_definition(text, pos)
            continue
        return False

_GQL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["query"]},
        "query": {"type": "string", "description": "GraphQL query or mutation."},
        "variables": {"type": "object"},
        "confirm": {"type": "boolean", "description": "required for mutations."},
    },
    "required": ["op", "query"],
}


def make_graphql_tool(
    *,
    name: str,
    base_url_env: str,
    token_env: str,
    description: str,
    token_header: str = "Authorization",
    scheme: str = "Bearer",
    basic: bool = False,
    extra_headers_env: dict[str, str] | None = None,
) -> Tool:
    """Build a GraphQL connector (single POST endpoint). Mutations are
    confirm-gated; queries run."""

    def _config() -> tuple[str, str]:
        return _env_config(name, base_url_env, token_env)

    def _run(args: dict[str, Any]) -> str:
        q = (args.get("query") or "").strip()
        if not q:
            return "ERROR: query is required"
        try:
            import httpx  # noqa: F401
        except ImportError:
            return "ERROR: httpx not installed. Run: pip install 'maverick-agent[issue-trackers]'"
        if _graphql_has_mutation(q) and not as_bool(args.get("confirm")):
            return "DRY RUN: GraphQL mutation. Re-run with confirm=true."
        variables = args.get("variables") if isinstance(args.get("variables"), dict) else {}
        try:
            base, tok = _config()
            # Enterprise mode: a GraphQL connector POSTs agent-supplied query +
            # variables to a third-party host -- hold it to the egress boundary
            # too (the REST factory already does this).
            from ..enterprise import enterprise_egress_denial
            deny = enterprise_egress_denial(base, tool=name)
            if deny:
                return f"ERROR: {deny}"
            # Same SSRF-safe path as the REST branch: pin the host IP and keep
            # redirects off (the old httpx.post relied on httpx's default and had
            # no IP-pinning), so the bearer token can't be redirected/rebound to
            # an internal address. On-prem opts in via MAVERICK_FETCH_ALLOW_PRIVATE=1.
            from ._ssrf import BlockedHost, safe_client
            headers = _build_auth_headers(
                tok, basic=basic, token_header=token_header, scheme=scheme,
                extra_headers_env=extra_headers_env,
            )
            try:
                with safe_client(base, timeout=30.0) as client:
                    r = client.post(base, headers=headers,
                                    json={"query": q, "variables": variables})
            except BlockedHost as e:
                return f"ERROR: blocked host (SSRF guard): {e}"
            try:
                data = r.json()
            except ValueError:
                return f"ERROR: graphql ({r.status_code}): {(r.text or '')[:500]}"
            if r.status_code >= 400 or (isinstance(data, dict) and data.get("errors")):
                return f"ERROR: graphql ({r.status_code}): {data.get('errors', data)}"
            return json.dumps(data.get("data", data), default=str)[:4000]
        except RuntimeError as e:
            return f"ERROR: {e}"
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {name} request failed: {type(e).__name__}: {e}"

    return Tool(name=name, description=description, input_schema=_GQL_SCHEMA, fn=_run)

