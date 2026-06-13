"""Out-of-process model proxy (roadmap: 2027 H2 safety).

The agent process holds the provider API keys it uses to call models. If that
process is prompt-injected or otherwise compromised, those keys are in reach.
This is the mitigation: run a tiny proxy **in a separate process** that holds
the key, and point the provider's ``base_url`` at it. The agent sends requests
with no usable credential; the proxy strips whatever the agent sent, injects
the real key, and forwards to the upstream. The key never lives in the agent's
address space.

It is also the natural central chokepoint for egress control: the proxy only
forwards to its single configured ``upstream`` host (an SSRF guard — a
compromised agent can't aim it at an arbitrary URL), and is the one place to
add per-call rate/audit policy later.

The security-critical part is :func:`build_request` (drop the client's auth +
hop-by-hop headers, inject the proxy's key in the upstream's scheme, refuse a
host outside the allow-set) — pure and exhaustively tested. The HTTP listener
(:func:`serve`, ``python -m maverick.model_proxy``) is a thin stdlib shell.

Config: ``[model_proxy]`` (``upstream`` / ``listen`` / ``auth_style`` /
``client_token`` / ``allowed_routes``) with the key from the proxy's **own**
environment (``MAVERICK_PROXY_KEY``) so it is never in the agent's config. The
listener requires a client bearer token (``MAVERICK_PROXY_CLIENT_TOKEN``) and
only forwards model-inference routes by default, so a reachable local service is
not a general provider-key oracle. Responses are buffered (an SSE stream is
forwarded whole), which keeps the proxy simple and correct; token-by-token relay
is a later refinement.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from .config import load_config

log = logging.getLogger(__name__)

# Headers that are connection-specific and must NOT be forwarded, plus the
# client-supplied credential headers the proxy replaces with its own.
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
})
_AUTH_HEADERS = frozenset({"authorization", "x-api-key", "api-key"})

DEFAULT_PORT = 8765
DEFAULT_ALLOWED_ROUTES = frozenset({
    # Anthropic Messages API (+ token counting).
    "POST /v1/messages",
    "POST /v1/messages/count_tokens",
    # OpenAI / OpenAI-compatible inference APIs.
    "POST /v1/chat/completions",
    "POST /v1/responses",
    "POST /v1/completions",
    "POST /v1/embeddings",
})
_PROXY_TOKEN_HEADER = "x-maverick-proxy-token"


@dataclass(frozen=True)
class ProxyConfig:
    upstream: str
    api_key: str
    listen_host: str = "127.0.0.1"
    listen_port: int = DEFAULT_PORT
    auth_style: str = "bearer"          # "bearer" | "x-api-key"
    allow_hosts: frozenset[str] = frozenset()  # empty == {upstream host}
    # Shared secret clients must present to the proxy. It is intentionally not
    # the provider key; use it as the agent-side provider api_key/base credential.
    client_token: str = ""
    # "METHOD /path" specs. Empty means the safe model-inference defaults above.
    allowed_routes: frozenset[str] = frozenset()

    def allowed(self) -> frozenset[str]:
        if self.allow_hosts:
            return self.allow_hosts
        host = urlparse(self.upstream).hostname
        return frozenset({host}) if host else frozenset()


def config_from_env() -> ProxyConfig | None:
    """Build the proxy config (``[model_proxy]`` + ``MAVERICK_PROXY_*``).

    Returns None when not configured (no upstream) — the caller reports it.
    The key is read from the proxy process's env, never from agent config.
    """
    upstream = os.environ.get("MAVERICK_PROXY_UPSTREAM", "").strip()
    key = os.environ.get("MAVERICK_PROXY_KEY", "").strip()
    listen = os.environ.get("MAVERICK_PROXY_LISTEN", "").strip()
    auth_style = os.environ.get("MAVERICK_PROXY_AUTH_STYLE", "").strip().lower()
    client_token = os.environ.get("MAVERICK_PROXY_CLIENT_TOKEN", "").strip()
    allowed_routes = _parse_allowed_routes(
        os.environ.get("MAVERICK_PROXY_ALLOWED_ROUTES", "")
    )
    if not upstream or not auth_style or not client_token or not allowed_routes:
        try:
            cfg = (load_config() or {}).get("model_proxy") or {}
            upstream = upstream or str(cfg.get("upstream") or "").strip()
            listen = listen or str(cfg.get("listen") or "").strip()
            auth_style = auth_style or str(cfg.get("auth_style") or "").strip().lower()
            client_token = client_token or str(cfg.get("client_token") or "").strip()
            if not allowed_routes:
                allowed_routes = _parse_allowed_routes(cfg.get("allowed_routes") or ())
        except Exception:  # pragma: no cover -- config never blocks startup
            pass
    if not upstream:
        return None
    host, port = _split_listen(listen)
    return ProxyConfig(
        upstream=upstream,
        api_key=key,
        listen_host=host,
        listen_port=port,
        auth_style=auth_style if auth_style in ("bearer", "x-api-key") else "bearer",
        client_token=client_token,
        allowed_routes=allowed_routes,
    )


def _parse_allowed_routes(value) -> frozenset[str]:
    if not value:
        return frozenset()
    if isinstance(value, str):
        raw = value.replace("\n", ",").split(",")
    else:
        raw = value
    routes = set()
    for item in raw:
        route = str(item or "").strip()
        if not route:
            continue
        parts = route.split(None, 1)
        if len(parts) != 2:
            continue
        method, path = parts[0].upper(), parts[1].strip()
        if not path.startswith("/"):
            path = f"/{path}"
        routes.add(f"{method} {path}")
    return frozenset(routes)


def _configured_routes(config: ProxyConfig) -> frozenset[str]:
    return config.allowed_routes or DEFAULT_ALLOWED_ROUTES


def route_allowed(config: ProxyConfig, method: str, path: str) -> bool:
    clean_path = urlparse(path).path or "/"
    if not clean_path.startswith("/"):
        clean_path = f"/{clean_path}"
    return f"{method.upper()} {clean_path}" in _configured_routes(config)


def authenticate(config: ProxyConfig, headers: dict[str, str]) -> bool:
    if not config.client_token:
        return False
    lowered = {k.lower(): v for k, v in headers.items()}
    bearer = lowered.get("authorization", "").strip()
    if bearer == f"Bearer {config.client_token}":
        return True
    return lowered.get(_PROXY_TOKEN_HEADER, "").strip() == config.client_token


def _split_listen(listen: str) -> tuple[str, int]:
    if not listen:
        return "127.0.0.1", DEFAULT_PORT
    if ":" in listen:
        host, _, port = listen.rpartition(":")
        try:
            return (host or "127.0.0.1"), int(port)
        except ValueError:
            return "127.0.0.1", DEFAULT_PORT
    return listen, DEFAULT_PORT


def build_request(config: ProxyConfig, path: str,
                  headers: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Transform a client request into the upstream request.

    Drops the client's auth + hop-by-hop headers and injects the proxy's key in
    the upstream's expected scheme. Raises ``ValueError`` if the resolved host
    is outside the allow-set (SSRF guard). Returns ``(url, headers)``.
    """
    url = config.upstream.rstrip("/") + "/" + path.lstrip("/")
    host = urlparse(url).hostname
    allowed = config.allowed()
    if host not in allowed:
        raise ValueError(f"upstream host {host!r} not in allow-set {sorted(allowed)}")
    out = {k: v for k, v in headers.items()
           if k.lower() not in _HOP_BY_HOP and k.lower() not in _AUTH_HEADERS}
    if config.auth_style == "x-api-key":
        out["x-api-key"] = config.api_key
    else:
        out["Authorization"] = f"Bearer {config.api_key}"
    return url, out


def forward(config: ProxyConfig, method: str, path: str,
            headers: dict[str, str], body: bytes, *,
            client=None, timeout: float = 600.0) -> tuple[int, dict[str, str], bytes]:
    """Forward a request upstream with the proxy's key. Returns
    ``(status, headers, body)``. Response is buffered."""
    url, fwd_headers = build_request(config, path, headers)
    if client is None:
        import httpx
        client = httpx
    resp = client.request(method, url, headers=fwd_headers, content=body or b"",
                          timeout=timeout)
    resp_headers = {k: v for k, v in dict(resp.headers).items()
                    if k.lower() not in _HOP_BY_HOP}
    return resp.status_code, resp_headers, resp.content


def handle(config: ProxyConfig, method: str, path: str,
           headers: dict[str, str], body: bytes, *,
           client=None) -> tuple[int, dict[str, str], bytes]:
    """Whole request handling: forward, or a clean error response. Never raises
    into the listener."""
    if not authenticate(config, headers):
        return 401, {"Content-Type": "text/plain"}, b"proxy authentication required"
    if not route_allowed(config, method, path):
        return 403, {"Content-Type": "text/plain"}, b"model proxy route not allowed"
    try:
        return forward(config, method, path, headers, body, client=client)
    except ValueError as e:  # blocked host / bad request
        return 403, {"Content-Type": "text/plain"}, str(e).encode("utf-8")
    except Exception as e:  # pragma: no cover -- upstream/network error
        log.warning("model proxy forward failed: %s", e)
        return 502, {"Content-Type": "text/plain"}, f"proxy error: {e}".encode()


def serve(config: ProxyConfig) -> None:  # pragma: no cover -- socket server
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _do(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            status, headers, out = handle(
                config, method, self.path, dict(self.headers), body)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def do_GET(self):
            self._do("GET")

        def do_POST(self):
            self._do("POST")

        def log_message(self, *a):  # quiet by default
            log.debug("proxy: %s", a[0] % a[1:] if len(a) > 1 else a[0])

    srv = ThreadingHTTPServer((config.listen_host, config.listen_port), _Handler)
    log.info("model proxy on %s:%d -> %s", config.listen_host,
             config.listen_port, config.upstream)
    srv.serve_forever()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- CLI shell
    import argparse
    p = argparse.ArgumentParser(
        prog="maverick.model_proxy",
        description="Out-of-process model proxy (holds the key the agent doesn't).")
    p.add_argument("--check", action="store_true",
                   help="validate config and exit without listening")
    args = p.parse_args(argv)
    config = config_from_env()
    if config is None:
        print("ERROR: no upstream configured "
              "(MAVERICK_PROXY_UPSTREAM or [model_proxy] upstream)")
        return 1
    if not config.client_token:
        print("ERROR: MAVERICK_PROXY_CLIENT_TOKEN or [model_proxy] client_token "
              "is required")
        return 1
    if not config.api_key:
        print("WARNING: MAVERICK_PROXY_KEY is empty; forwarded requests will be "
              "unauthenticated upstream")
    if args.check:
        print(f"OK: {config.listen_host}:{config.listen_port} -> {config.upstream} "
              f"(auth={config.auth_style})")
        return 0
    serve(config)
    return 0


__all__ = ["ProxyConfig", "config_from_env", "build_request", "forward",
           "handle", "serve", "authenticate", "route_allowed"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
