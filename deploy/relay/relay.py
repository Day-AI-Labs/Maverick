#!/usr/bin/env python3
"""Self-hosted Maverick relay (roadmap: 2027 H2 distribution — "self-hosted relay reference").

A thin, dependency-free edge service that accepts a simple inbound POST and
forwards it as a properly HMAC-signed request to a Maverick dashboard's
``/webhook/start``. This is the self-hostable counterpart to a hosted bridge
(e.g. the glasses/wearable adapter): run it on your own box/VPS/edge instead of
depending on someone's cloud function.

It signs exactly the way ``maverick.webhooks`` verifies:
    material   = f"{timestamp}.".encode() + body
    signature  = "sha256=" + hmac_sha256(secret, material).hexdigest()
sent as ``X-Maverick-Signature`` + ``X-Maverick-Timestamp``.

Config via env:
    MAVERICK_RELAY_SECRET    shared [webhooks] secret (required)
    MAVERICK_RELAY_TARGET    dashboard base URL (default http://127.0.0.1:8765)
    MAVERICK_RELAY_PORT      listen port (default 8799)
    MAVERICK_RELAY_HOST      listen host (default 127.0.0.1)
    MAVERICK_RELAY_TOKEN     required bearer the *caller* must present

    POST /relay  {"title": "...", "description": "...", "budget": 5.0}
    -> {"goal_id": <int>}

Stdlib only. Run:  python deploy/relay/relay.py
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TARGET = os.environ.get("MAVERICK_RELAY_TARGET", "http://127.0.0.1:8765").rstrip("/")
SECRET = os.environ.get("MAVERICK_RELAY_SECRET", "")
PORT = int(os.environ.get("MAVERICK_RELAY_PORT", "8799"))
HOST = os.environ.get("MAVERICK_RELAY_HOST", "127.0.0.1")
CALLER_TOKEN = os.environ.get("MAVERICK_RELAY_TOKEN", "")
_MAX_BODY = 64 * 1024


def sign(body: bytes, secret: str, timestamp: str) -> str:
    material = f"{timestamp}.".encode() + body
    return "sha256=" + hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()


def forward(payload: dict) -> tuple[int, bytes]:
    body = json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()))
    req = urllib.request.Request(
        f"{TARGET}/webhook/start",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Maverick-Signature": sign(body, SECRET, ts),
            "X-Maverick-Timestamp": ts,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:  # surface the dashboard's error verbatim
        return e.code, e.read()
    except OSError as e:
        return 502, json.dumps({"error": f"relay->dashboard: {e}"}).encode()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 (stdlib API)
        if self.path.rstrip("/") != "/relay":
            return self._send(404, b'{"error":"not found"}')
        if not CALLER_TOKEN:
            return self._send(503, b'{"error":"relay token is not configured"}')
        auth = self.headers.get("Authorization", "")
        if not hmac.compare_digest(auth, f"Bearer {CALLER_TOKEN}"):
            return self._send(401, b'{"error":"unauthorized"}')
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > _MAX_BODY:
            return self._send(413, b'{"error":"bad body size"}')
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, b'{"error":"invalid json"}')
        title = (data.get("title") or "").strip()
        if not title:
            return self._send(400, b'{"error":"title is required"}')
        payload = {"title": title}
        if data.get("description"):
            payload["description"] = str(data["description"])
        if data.get("budget") is not None:
            payload["budget"] = data["budget"]
        code, out = forward(payload)
        self._send(code, out)

    def log_message(self, fmt: str, *args) -> None:
        # Minimal access log: request line + status only. Never logs headers or
        # body, so the caller bearer and the HMAC signing secret are not
        # written out. On by default (an internet-adjacent forwarder with no
        # request log has no audit trail); set MAVERICK_RELAY_ACCESS_LOG=0 to
        # silence.
        if os.environ.get("MAVERICK_RELAY_ACCESS_LOG", "1") == "0":
            return
        line = fmt % args if args else fmt
        sys.stderr.write(
            f"{self.address_string()} - - [{self.log_date_time_string()}] {line}\n"
        )


def main() -> int:
    if not SECRET:
        raise SystemExit("Set MAVERICK_RELAY_SECRET (matches the dashboard's [webhooks] secret).")
    if not CALLER_TOKEN:
        raise SystemExit("Set MAVERICK_RELAY_TOKEN (required bearer token for relay callers).")
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Maverick relay on {HOST}:{PORT} -> {TARGET}/webhook/start")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
