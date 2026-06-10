"""Universal share link + cross-device handoff (roadmap: 2028 H2 UX).

Two token mechanisms over one HMAC core (the webhooks signing pattern):

* **Share link** — a signed, *expiring, read-only* token referencing a goal:
  ``share://<goal_id>.<expires>.<sig>``. The dashboard verifies and renders
  the run read-only; the token carries NO content (the viewer must reach the
  deployment — a leaked link to an outsider with no network path to the
  dashboard reveals only a goal id). Constant-time verification; expiry and
  signature both fail closed.
* **Device handoff** — a *one-time* code moving a session between the user's
  devices: ``pack()`` signs {goal_id, conversation_id, channel, user_id,
  expires, nonce}; ``claim()`` verifies and **consumes** the nonce (a second
  claim is refused), so a stolen code that was already used is dead. Short
  default TTL (5 minutes).

The secret is ``[sharing] secret`` (env ``MAVERICK_SHARE_SECRET``); with no
secret configured, BOTH mechanisms refuse to mint or verify — there is no
unsigned mode. Nonce store injectable (defaults to a data_dir JSON, 0600).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets as _secrets
import time
from pathlib import Path


def _secret() -> str | None:
    env = os.environ.get("MAVERICK_SHARE_SECRET", "").strip()
    if env:
        return env
    try:
        from .config import load_config
        s = ((load_config() or {}).get("sharing") or {}).get("secret")
        return str(s).strip() if s else None
    except Exception:  # pragma: no cover -- config never blocks
        return None


def _sign(material: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), material.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:32]


class SharingDisabled(RuntimeError):
    """No [sharing] secret configured: nothing is minted or verified."""


def _require_secret() -> str:
    s = _secret()
    if not s:
        raise SharingDisabled(
            "sharing is disabled: set [sharing] secret (or "
            "MAVERICK_SHARE_SECRET) to mint/verify share links")
    return s


# -- share links ----------------------------------------------------------

def mint_share_link(goal_id: int, *, ttl_seconds: float = 7 * 86400.0,
                    now: float | None = None) -> str:
    secret = _require_secret()
    expires = int(float(now if now is not None else time.time()) + ttl_seconds)
    material = f"share:{int(goal_id)}:{expires}"
    return f"{int(goal_id)}.{expires}.{_sign(material, secret)}"


def verify_share_link(token: str, *, now: float | None = None) -> int:
    """Return the goal id for a valid token; raise ``ValueError`` otherwise."""
    secret = _require_secret()
    parts = (token or "").strip().split(".")
    if len(parts) != 3:
        raise ValueError("malformed share token")
    gid_s, exp_s, sig = parts
    try:
        gid, expires = int(gid_s), int(exp_s)
    except ValueError as e:
        raise ValueError("malformed share token") from e
    expected = _sign(f"share:{gid}:{expires}", secret)
    if not hmac.compare_digest(sig, expected):
        raise ValueError("invalid share token signature")
    if float(now if now is not None else time.time()) >= expires:
        raise ValueError("share token expired")
    return gid


# -- device handoff -------------------------------------------------------

def _nonce_store_path() -> Path:
    from .paths import data_dir
    return data_dir("handoff_nonces.json")


def _load_nonces(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_nonces(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover
        pass


def pack_handoff(session: dict, *, ttl_seconds: float = 300.0,
                 now: float | None = None) -> str:
    """Mint a one-time handoff code for ``session`` (goal/conversation ids,
    channel, user_id — NO secrets ride in the code)."""
    secret = _require_secret()
    payload = {
        "goal_id": session.get("goal_id"),
        "conversation_id": session.get("conversation_id"),
        "channel": session.get("channel"),
        "user_id": session.get("user_id"),
        "expires": int(float(now if now is not None else time.time()) + ttl_seconds),
        "nonce": _secrets.token_hex(8),
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    import base64
    b64 = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{b64}.{_sign(body, secret)}"


def claim_handoff(code: str, *, now: float | None = None,
                  nonce_path: Path | None = None) -> dict:
    """Verify + CONSUME a handoff code; a second claim of the same nonce is
    refused. Returns the session dict."""
    secret = _require_secret()
    parts = (code or "").strip().split(".")
    if len(parts) != 2:
        raise ValueError("malformed handoff code")
    import base64
    b64, sig = parts
    try:
        pad = "=" * (-len(b64) % 4)
        body = base64.urlsafe_b64decode(b64 + pad).decode("utf-8")
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError("malformed handoff code") from e
    if not hmac.compare_digest(sig, _sign(body, secret)):
        raise ValueError("invalid handoff signature")
    if float(now if now is not None else time.time()) >= float(payload.get("expires", 0)):
        raise ValueError("handoff code expired")
    nonce = str(payload.get("nonce") or "")
    path = nonce_path or _nonce_store_path()
    used = _load_nonces(path)
    if nonce in used:
        raise ValueError("handoff code already claimed (one-time use)")
    ts = float(now if now is not None else time.time())
    # prune expired nonces while we hold the file
    used = {n: e for n, e in used.items() if float(e) > ts}
    used[nonce] = payload["expires"]
    _save_nonces(path, used)
    payload.pop("nonce", None)
    payload.pop("expires", None)
    return payload


__all__ = ["SharingDisabled", "mint_share_link", "verify_share_link",
           "pack_handoff", "claim_handoff"]
