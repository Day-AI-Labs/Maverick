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

from . import Tool, as_bool

_WRITE_OPS = {"post", "put", "patch", "delete"}

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


def make_rest_tool(
    *,
    name: str,
    base_url_env: str,
    token_env: str,
    description: str,
    token_header: str = "Authorization",
    scheme: str = "Bearer",
    basic: bool = False,
) -> Tool:
    """Build a thin authenticated-REST ``Tool``.

    Auth modes:
      - ``basic=True``  -> ``Authorization: Basic b64(token)`` (token is
        ``user:pass``; a bare token is treated as ``token:x``, the API-key
        convention used by Freshdesk / Greenhouse / Lever / BambooHR).
      - else ``{token_header}: {scheme} {token}`` (``scheme=""`` sends the raw
        token, e.g. Tableau's ``X-Tableau-Auth``).
    """

    def _config() -> tuple[str, str]:
        base = os.environ.get(base_url_env, "").strip().rstrip("/")
        tok = os.environ.get(token_env, "").strip()
        if not base or not tok:
            raise RuntimeError(f"{name} requires {base_url_env} + {token_env}.")
        return base, tok

    def _headers(tok: str) -> dict[str, str]:
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        if basic:
            raw = tok if ":" in tok else f"{tok}:x"
            h["Authorization"] = "Basic " + base64.b64encode(raw.encode()).decode("ascii")
        else:
            h[token_header] = f"{scheme} {tok}".strip()
        return h

    def _norm(path: str) -> str:
        p = path.strip()
        return p if p.startswith("/") else "/" + p

    def _run(args: dict[str, Any]) -> str:
        op = (args.get("op") or "").strip().lower()
        if op not in ("get", "post", "put", "patch", "delete"):
            return f"ERROR: op must be get/post/put/patch/delete (got {op!r})"
        path = (args.get("path") or "").strip()
        if not path:
            return "ERROR: path is required"
        try:
            import httpx  # noqa: F401
        except ImportError:
            return "ERROR: httpx not installed. Run: pip install 'maverick-agent[issue-trackers]'"
        if op in _WRITE_OPS and not as_bool(args.get("confirm")):
            return f"DRY RUN: would {op.upper()} {_norm(path)}. Re-run with confirm=true."
        params = args.get("params") if isinstance(args.get("params"), dict) else None
        body = args.get("body") if isinstance(args.get("body"), dict) else None
        try:
            base, tok = _config()
            url = f"{base}{_norm(path)}"
            # Enterprise mode: a connector POSTs agent-supplied content to a
            # third-party SaaS host -- hold it to the egress boundary too.
            from ..enterprise import enterprise_egress_denial
            deny = enterprise_egress_denial(url, tool=name)
            if deny:
                return f"ERROR: {deny}"
            import httpx
            r = httpx.request(op.upper(), url, headers=_headers(tok),
                              params=params or None, json=body, timeout=30.0)
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

    return Tool(name=name, description=description, input_schema=_SCHEMA, fn=_run)


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
) -> Tool:
    """Build a GraphQL connector (single POST endpoint). Mutations (the query
    text starts with ``mutation``) are confirm-gated; queries run."""

    def _config() -> tuple[str, str]:
        base = os.environ.get(base_url_env, "").strip().rstrip("/")
        tok = os.environ.get(token_env, "").strip()
        if not base or not tok:
            raise RuntimeError(f"{name} requires {base_url_env} + {token_env}.")
        return base, tok

    def _run(args: dict[str, Any]) -> str:
        q = (args.get("query") or "").strip()
        if not q:
            return "ERROR: query is required"
        try:
            import httpx  # noqa: F401
        except ImportError:
            return "ERROR: httpx not installed. Run: pip install 'maverick-agent[issue-trackers]'"
        if q.lstrip("(").lower().startswith("mutation") and not as_bool(args.get("confirm")):
            return "DRY RUN: GraphQL mutation. Re-run with confirm=true."
        variables = args.get("variables") if isinstance(args.get("variables"), dict) else {}
        try:
            base, tok = _config()
            import httpx
            headers = {"Content-Type": "application/json",
                       token_header: f"{scheme} {tok}".strip()}
            r = httpx.post(base, headers=headers,
                           json={"query": q, "variables": variables}, timeout=30.0)
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

