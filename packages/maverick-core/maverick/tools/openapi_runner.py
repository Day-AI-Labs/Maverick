"""OpenAPI runner — call any REST endpoint by spec.

Given an OpenAPI 3 spec (URL or local file) the agent can:
  - list the operations the API exposes,
  - look up the schema of a specific operation,
  - invoke an operation with named parameters.

Lightweight: no codegen, no client class library. We parse the spec
once (cached by path/URL), then synthesize requests on demand. JSON
specs are first-class; YAML works when ``pyyaml`` is installed.

ops:
  - list_ops(spec)                 — every {method, path, opId, summary}
  - describe(spec, op_id)          — params + request body schema
  - call(spec, op_id, params, body, base_url)
                                   — issue the request, return response

Auth is opt-in via standard headers in ``headers={...}`` on call().

This wraps tens of thousands of public + private APIs without us
writing a tool per API. Limits: no OAuth flow handling (caller
provides bearer/api-key in ``headers``); no multipart upload;
only application/json bodies.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_OAS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["list_ops", "describe", "call"]},
        "spec": {
            "type": "string",
            "description": "Spec source: URL (http(s)://) or local file path.",
        },
        "op_id": {"type": "string", "description": "operationId from the spec."},
        "params": {
            "type": "object",
            "description": "Named values for path/query parameters.",
        },
        "body": {
            "description": "Request body (JSON-serializable) for POST/PUT/PATCH.",
        },
        "headers": {
            "type": "object",
            "description": "Extra HTTP headers (auth tokens etc.).",
        },
        "base_url": {
            "type": "string",
            "description": "Override the spec's servers[0].url.",
        },
    },
    "required": ["op", "spec"],
}


_spec_lock = threading.Lock()
_spec_cache: dict[str, dict] = {}


def _load_spec(source: str) -> dict:
    with _spec_lock:
        if source in _spec_cache:
            return _spec_cache[source]
    if source.startswith(("http://", "https://")):
        from ._ssrf import safe_client
        # safe_client validates the host and pins the connection to the
        # resolved public IP (closes the DNS-rebinding TOCTOU).
        with safe_client(source, timeout=30.0) as client:
            r = client.get(source)
        r.raise_for_status()
        text = r.text
    else:
        with open(source, encoding="utf-8") as f:
            text = f.read()
    # Try JSON first; fall back to YAML.
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as e:
            raise RuntimeError(
                "Spec is YAML and pyyaml not installed. "
                "Install pyyaml or convert to JSON."
            ) from e
        data = yaml.safe_load(text)
    if not isinstance(data, dict) or "paths" not in data:
        raise RuntimeError("OpenAPI spec missing 'paths'")
    with _spec_lock:
        _spec_cache[source] = data
    return data


def _walk_ops(spec: dict):
    paths = spec.get("paths") or {}
    methods = ("get", "post", "put", "patch", "delete", "options", "head")
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in methods:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            yield method.upper(), path, op


def _resolve_ref(spec: dict, node: Any, _seen: frozenset[str] = frozenset()) -> Any:
    """Resolve an internal JSON Reference (``{"$ref": "#/..."}``) within ``spec``.

    Returns the referenced object (following a chain transitively), or the node
    unchanged when it isn't a ``$ref``, points outside the document, is
    unresolvable, or would cycle. Never raises -- ref problems must not break
    describe/call; an unresolved external ref just shows/sends as-is.
    """
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/") or ref in _seen:
        return node
    target: Any = spec
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")  # JSON-pointer unescape
        if isinstance(target, dict) and part in target:
            target = target[part]
        else:
            return node  # unresolvable pointer: leave the node as-is
    return _resolve_ref(spec, target, _seen | {ref})


def _merged_parameters(spec: dict, path_item: dict, op: dict) -> list[dict]:
    """Effective parameters for an operation: path-item-level + operation-level,
    each ``$ref``-resolved, keyed by (name, location) with operation-level
    overriding path-level (per the OpenAPI spec).
    """
    merged: dict[tuple, dict] = {}
    for source in (path_item.get("parameters") or [], op.get("parameters") or []):
        for raw in source:
            p = _resolve_ref(spec, raw)
            if isinstance(p, dict):
                merged[(p.get("name"), p.get("in"))] = p
    return list(merged.values())


def _op_list(spec_src: str) -> str:
    spec = _load_spec(spec_src)
    rows: list[str] = []
    for method, path, op in _walk_ops(spec):
        op_id = op.get("operationId") or f"{method.lower()}_{path}"
        summary = (op.get("summary") or "").strip()
        rows.append(
            f"  {method:>6}  {path:<40}  {op_id}  — {summary[:60]}"
        )
    if not rows:
        return "no operations"
    return "\n".join(rows)


def _find_op(spec: dict, op_id: str) -> tuple[str, str, dict] | None:
    for method, path, op in _walk_ops(spec):
        if (op.get("operationId") or "") == op_id:
            return method, path, op
    return None


def _op_describe(spec_src: str, op_id: str) -> str:
    spec = _load_spec(spec_src)
    found = _find_op(spec, op_id)
    if not found:
        return f"op {op_id!r} not found"
    method, path, op = found
    path_item = (spec.get("paths") or {}).get(path) or {}
    lines = [f"{method} {path}",
             f"  summary: {op.get('summary', '')}"]
    for p in _merged_parameters(spec, path_item, op):
        loc = p.get("in", "?")
        name = p.get("name", "?")
        required = "*" if p.get("required") else ""
        schema = _resolve_ref(spec, p.get("schema") or {}).get("type", "?")
        lines.append(f"  param ({loc}): {name}{required} : {schema}")
    body = _resolve_ref(spec, op.get("requestBody") or {})
    if body:
        content = (body.get("content") or {}).get("application/json") or {}
        schema = _resolve_ref(spec, content.get("schema") or {})
        lines.append("  body (application/json): " + json.dumps(schema, default=str)[:400])
    return "\n".join(lines)


def _resolve_base(spec: dict, override: str) -> str:
    if override:
        return override.rstrip("/")
    servers = spec.get("servers") or []
    if servers and isinstance(servers[0], dict):
        return str(servers[0].get("url", "")).rstrip("/")
    return ""


def _op_call(
    spec_src: str,
    op_id: str,
    params: dict | None,
    body: Any,
    headers: dict | None,
    base_url: str,
) -> str:
    spec = _load_spec(spec_src)
    found = _find_op(spec, op_id)
    if not found:
        return f"op {op_id!r} not found"
    method, path, op = found
    params = params or {}
    # Substitute path params from `params`.
    used: set[str] = set()
    out_path = path
    path_item = (spec.get("paths") or {}).get(path) or {}
    for p in _merged_parameters(spec, path_item, op):
        if p.get("in") == "path":
            name = p.get("name", "")
            if name in params:
                out_path = out_path.replace("{" + name + "}", str(params[name]))
                used.add(name)
            elif p.get("required"):
                return f"ERROR: required path param {name!r} not provided"
    # Remaining params -> query.
    query = {k: v for k, v in params.items() if k not in used}
    base = _resolve_base(spec, base_url)
    url = (base or "") + out_path
    if not url.startswith(("http://", "https://")):
        return "ERROR: no base URL and op has no absolute servers[0]"
    req_kwargs = {
        "headers": headers or {},
        "params": query,
    }
    if body is not None and method in {"POST", "PUT", "PATCH"}:
        req_kwargs["json"] = body
    from ._ssrf import safe_client
    # Validate + pin the connection to the resolved public IP so a rebinding
    # resolver can't redirect the call to an internal/metadata address.
    with safe_client(url, timeout=60.0) as client:
        r = client.request(method, url, **req_kwargs)
    text = r.text or ""
    truncated = text[:3000] + (" ... (truncated)" if len(text) > 3000 else "")
    return f"HTTP {r.status_code}\n{truncated}"


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    spec_src = (args.get("spec") or "").strip()
    if not spec_src:
        return "ERROR: spec is required (URL or local path)"
    try:
        if op == "list_ops":
            return _op_list(spec_src)
        if op == "describe":
            op_id = (args.get("op_id") or "").strip()
            if not op_id:
                return "ERROR: describe requires op_id"
            return _op_describe(spec_src, op_id)
        if op == "call":
            try:
                import httpx  # noqa: F401
            except ImportError:
                return "ERROR: httpx not installed. Run: pip install 'maverick-agent[issue-trackers]'"
            op_id = (args.get("op_id") or "").strip()
            if not op_id:
                return "ERROR: call requires op_id"
            return _op_call(
                spec_src, op_id,
                args.get("params") if isinstance(args.get("params"), dict) else None,
                args.get("body"),
                args.get("headers") if isinstance(args.get("headers"), dict) else None,
                (args.get("base_url") or "").strip(),
            )
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        from ._ssrf import BlockedHost
        if isinstance(e, BlockedHost):
            return f"ERROR: refusing to fetch (blocked host): {e}"
        return f"ERROR: openapi request failed: {type(e).__name__}: {e}"
    return f"ERROR: unknown op {op!r}"


def openapi_runner() -> Tool:
    return Tool(
        name="openapi_runner",
        description=(
            "Call any REST API by OpenAPI 3 spec. ops: list_ops "
            "(enumerate operationIds), describe (params + body "
            "schema for one op), call (issue the request, returns "
            "HTTP status + body). Auth tokens go in headers. "
            "Spec URL is cached for the process."
        ),
        input_schema=_OAS_SCHEMA,
        fn=_run,
    )
