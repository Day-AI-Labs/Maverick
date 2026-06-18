"""Channel federation — forward channel messages between Maverick instances.

Reuses the signed-envelope primitives from :mod:`maverick.federation_envelope`
(one implementation; nothing duplicated). A forwarded message travels as::

    {"schema": "maverick-channel-fed/1", "origin", "to", "created_at",
     "channel", "user_id", "text", "pubkey", "key_id", "sig"}

  - ``user_id`` is **pseudonymized before it leaves this host**: an HMAC-SHA256
    of the real id under the per-pair ``secret`` from the peer's
    ``[federation] channel_peers`` entry (``"fed-" + hex[:16]``). The same user
    maps to a stable pseudonym per peer pair, and different pairs see different
    pseudonyms. No secret configured = no enqueue (privacy fail-closed).
  - ``to`` names the destination origin and is covered by the signature, so an
    envelope captured in transit cannot be replayed at a *different* peer.

Outbound: :class:`OutboundQueue` — a bounded on-disk queue (atomic 0600 JSON
under ``data_dir``; oldest entries drop when full, counted) flushed through an
**injected transport**: any ``send(envelope) -> None`` callable. Inbound: any
iterable of envelopes fed to :func:`apply_inbound` / :func:`apply_many`, which
verify the signature FAIL-CLOSED against the pinned key for the origin
(``[federation] channel_peers``), check the envelope is addressed to us, reject
a stale/future-dated or replayed envelope (signed ``created_at`` freshness
window + per-signature replay-nonce cache, so a captured envelope can't be
re-injected at this same peer), rate-limit per peer (token bucket, injected
clock), and hand a :class:`FedMessage` with ``channel="fed:<origin>"`` to the
normal channel handler (e.g. ``Server._handle_message``) — so federated traffic
flows through the same shield scans, tenancy, and budget caps as any other
channel.

**The HTTP binding is the operator's.** This module deliberately ships no
listener and opens no sockets; wire the transport however your deployment
talks (mTLS reverse proxy, message bus, ssh pipe)::

    # sender                                  # receiver (e.g. behind FastAPI)
    q = OutboundQueue()                       applier = InboundApplier(handler)
    enqueue(q, "ops-eu", ch, uid, text)       applier.apply(request_json)
    flush(q, send=my_http_post)

Config: ``[federation] channel_peers`` (pinned ``{origin, pubkey, secret}``
entries) and ``[federation] channel_rate_per_min`` (default 30 per peer).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .federation_envelope import (
    FederationError,
    local_origin,
    peer_allowlist,
    sign_envelope,
    valid_origin,
    verify_envelope,
)

log = logging.getLogger(__name__)

SCHEMA = "maverick-channel-fed/1"
MAX_TEXT_CHARS = 4000
MAX_USER_ID_CHARS = 64
DEFAULT_QUEUE_MAX = 256
DEFAULT_RATE_PER_MIN = 30.0
_MAX_BATCH = 1000
# Inbound freshness window: reject an envelope whose signed ``created_at`` is
# more than this far from now (stale or future-dated). Bounds how long a
# captured envelope stays replayable; generous by default so an at-least-once
# redelivery after a transient outage isn't dropped. Override via
# ``[federation] channel_max_age_seconds`` / MAVERICK_FEDERATION_CHANNEL_MAX_AGE.
DEFAULT_MAX_AGE_S = 3600.0


def pseudonymize(user_id: str, secret: str) -> str:
    """Stable per-pair pseudonym for a channel user id. Raises without a secret."""
    if not secret:
        raise FederationError("channel federation requires a per-pair secret to "
                              "pseudonymize user ids; refusing to forward raw ids")
    mac = hmac.new(secret.encode("utf-8"), str(user_id).encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return f"fed-{mac[:16]}"


def make_envelope(
    channel: str,
    user_id: str,
    text: str,
    *,
    peer: str,
    secret: str,
    origin: str | None = None,
    now: float | None = None,
) -> dict:
    """Build + sign one forwarded-message envelope addressed to ``peer``."""
    if not isinstance(channel, str) or not channel.strip():
        raise FederationError("channel is required")
    if not valid_origin(peer):
        raise FederationError(f"peer origin {peer!r} is malformed")
    from datetime import datetime, timezone
    ts = time.time() if now is None else now
    payload = {
        "schema": SCHEMA,
        "origin": origin or local_origin(),
        "to": peer,
        "created_at": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
        "channel": channel.strip()[:128],
        "user_id": pseudonymize(user_id, secret),
        "text": str(text)[:MAX_TEXT_CHARS],
    }
    return sign_envelope(payload)


# ---------------------------------------------------------------------------
# Outbound queue (bounded, on-disk, 0600)
# ---------------------------------------------------------------------------

class OutboundQueue:
    """Bounded FIFO of signed envelopes awaiting transport.

    One JSON file under ``data_dir`` (atomic replace, chmod 600 — the payloads
    are user messages). When full, the oldest entry is dropped and counted in
    the persisted ``dropped`` tally, so backpressure is visible, not silent.
    """

    def __init__(self, path: Path | None = None, max_len: int = DEFAULT_QUEUE_MAX):
        if path is None:
            from .paths import data_dir
            path = data_dir() / "channel_federation_outbox.json"
        self.path = Path(path)
        self.max_len = max(1, int(max_len))

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"items": [], "dropped": 0}
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            return {"items": [], "dropped": 0}
        data.setdefault("dropped", 0)
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:  # pragma: no cover
            pass

    def append(self, envelope: dict) -> None:
        data = self._load()
        data["items"].append(envelope)
        while len(data["items"]) > self.max_len:
            data["items"].pop(0)
            data["dropped"] = int(data.get("dropped", 0)) + 1
        self._save(data)

    def __len__(self) -> int:
        return len(self._load()["items"])

    @property
    def dropped(self) -> int:
        return int(self._load().get("dropped", 0))


def enqueue(
    queue: OutboundQueue,
    peer: str,
    channel: str,
    user_id: str,
    text: str,
    *,
    peers: dict[str, dict] | None = None,
    now: float | None = None,
) -> dict:
    """Pseudonymize, sign, and queue one message for ``peer``.

    The peer must be configured in ``[federation] channel_peers`` with a
    ``secret`` — otherwise this raises (never forwards a raw user id).
    """
    if peers is None:
        peers = peer_allowlist("channel_peers")
    entry = peers.get(peer)
    if entry is None:
        raise FederationError(f"peer {peer!r} is not in [federation] channel_peers")
    env = make_envelope(channel, user_id, text, peer=peer,
                        secret=str(entry.get("secret") or ""), now=now)
    queue.append(env)
    return env


def flush(queue: OutboundQueue, send: Callable[[dict], None]) -> int:
    """Drain the queue through the injected transport. Returns envelopes sent.

    At-least-once: an envelope is only removed after ``send`` returns; a send
    failure stops the flush and keeps the remainder (including the failed one)
    queued for retry.
    """
    data = queue._load()
    items = data["items"]
    sent = 0
    while items:
        try:
            send(items[0])
        except Exception as e:
            log.warning("channel federation: send failed after %d envelope(s): %s",
                        sent, e)
            break
        items.pop(0)
        sent += 1
    queue._save(data)
    return sent


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------

class TokenBucket:
    """Per-key token bucket over an injected monotonic clock."""

    def __init__(self, rate_per_min: float = DEFAULT_RATE_PER_MIN,
                 burst: float | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.rate = max(float(rate_per_min), 0.001) / 60.0  # tokens per second
        self.burst = float(burst) if burst else max(float(rate_per_min), 1.0)
        self.clock = clock
        self._state: dict[str, tuple[float, float]] = {}  # key -> (tokens, last)

    def allow(self, key: str) -> bool:
        now = self.clock()
        tokens, last = self._state.get(key, (self.burst, now))
        tokens = min(self.burst, tokens + (now - last) * self.rate)
        if tokens < 1.0:
            self._state[key] = (tokens, now)
            return False
        self._state[key] = (tokens - 1.0, now)
        return True


def default_limiter(clock: Callable[[], float] = time.monotonic) -> TokenBucket:
    """A TokenBucket configured from ``[federation] channel_rate_per_min``."""
    rate = DEFAULT_RATE_PER_MIN
    try:
        from .config import load_config
        raw = ((load_config() or {}).get("federation") or {}).get("channel_rate_per_min")
        if raw is not None:
            rate = max(0.001, float(raw))
    except Exception:  # pragma: no cover - config never blocks the limiter
        pass
    return TokenBucket(rate_per_min=rate, clock=clock)


def _default_max_age() -> float:
    """Inbound freshness window from env / ``[federation] channel_max_age_seconds``."""
    raw = os.environ.get("MAVERICK_FEDERATION_CHANNEL_MAX_AGE")
    if raw is None or str(raw).strip() == "":
        try:
            from .config import load_config
            val = ((load_config() or {}).get("federation") or {}).get(
                "channel_max_age_seconds")
            raw = None if val is None else str(val)
        except Exception:  # pragma: no cover - config never blocks the default
            raw = None
    if raw is None or str(raw).strip() == "":
        return DEFAULT_MAX_AGE_S
    try:
        return max(1.0, float(raw))
    except ValueError:
        return DEFAULT_MAX_AGE_S


def _parse_iso_epoch(value: object) -> float | None:
    """Parse an ISO-8601 ``created_at`` to epoch seconds; None if unparseable.

    A naive timestamp is treated as UTC (``make_envelope`` always emits a
    tz-aware UTC string, so this only matters for a malformed peer)."""
    if not isinstance(value, str) or not value:
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


@dataclass
class FedMessage:
    """The message handed to the normal channel handler.

    Duck-type compatible with channel adapter messages (``.channel`` /
    ``.user_id`` / ``.text``); ``channel`` is always ``"fed:<origin>"`` so
    downstream policy can tell federated traffic apart.
    """
    channel: str
    user_id: str
    text: str


class InboundApplier:
    """Verify-then-apply for inbound envelopes.

    ``handler`` is the injected seam to the normal channel handling path — a
    callable taking one :class:`FedMessage`. (For the async
    ``Server._handle_message``, the operator wraps it with their loop's
    scheduling; this module stays transport- and loop-agnostic.)
    """

    def __init__(
        self,
        handler: Callable[[FedMessage], object],
        *,
        peers: dict[str, dict] | None = None,
        limiter: TokenBucket | None = None,
        local: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_age_seconds: float | None = None,
        wall_clock: Callable[[], float] = time.time,
    ):
        self.handler = handler
        self._peers = peers
        self.limiter = limiter or default_limiter(clock)
        self.local = local or local_origin()
        self.max_age = (_default_max_age() if max_age_seconds is None
                        else max(1.0, float(max_age_seconds)))
        # Wall clock (not the limiter's monotonic clock) for the created_at
        # freshness comparison; injectable for tests.
        self._wall = wall_clock
        # Replay-nonce cache: a verified envelope's signature is a unique nonce
        # (created_at is inside the signed body). Age-pruned within the freshness
        # window and lock-guarded so a threaded inbound binding stays correct.
        self._seen_sigs: OrderedDict[str, float] = OrderedDict()
        self._seen_lock = threading.Lock()

    def _replay_seen(self, sig: str, now: float) -> bool:
        """Check-and-remember a verified signature; True if already seen.

        Prunes by AGE: an entry older than the freshness window can never be
        replayed (its envelope would fail the freshness check), so evicting it is
        safe and the live set is bounded by legitimate in-window peer volume."""
        if not sig:
            return False
        cutoff = now - self.max_age
        with self._seen_lock:
            while self._seen_sigs:
                _oldest, ts = next(iter(self._seen_sigs.items()))
                if ts >= cutoff:
                    break
                self._seen_sigs.popitem(last=False)
            if sig in self._seen_sigs:
                return True
            self._seen_sigs[sig] = now
            return False

    @property
    def peers(self) -> dict[str, dict]:
        return self._peers if self._peers is not None else peer_allowlist("channel_peers")

    def apply(self, envelope: object) -> dict:
        """Returns ``{"applied", "reason", "result"}``. Never raises on bad input."""
        ok, reason = verify_envelope(envelope, expected_schema=SCHEMA, peers=self.peers)
        if not ok:
            log.warning("channel federation: rejected inbound envelope: %s", reason)
            return {"applied": False, "reason": reason, "result": None}
        assert isinstance(envelope, dict)
        origin = envelope["origin"]
        if envelope.get("to") != self.local:
            return {"applied": False,
                    "reason": f"envelope addressed to {envelope.get('to')!r}, not "
                              f"{self.local!r} (replay across peers?)",
                    "result": None}
        # Agent Trust Plane: when engaged, the (signature-verified) origin must
        # also be a registered, inbound-permitted agent — so the trust registry
        # is the single allowlist, not just the [federation] channel_peers pins.
        # No-op when disengaged (kernel rule 1).
        from . import agent_trust
        decision = agent_trust.decide_inbound(origin)
        if decision.denied:
            agent_trust.record_denied(origin, decision, direction="inbound")
            return {"applied": False, "reason": decision.reason, "result": None}
        channel = envelope.get("channel")
        user_id = envelope.get("user_id")
        text = envelope.get("text")
        if not all(isinstance(v, str) and v for v in (channel, user_id, text)):
            return {"applied": False, "reason": "missing channel/user_id/text",
                    "result": None}
        # Freshness: created_at is inside the signed body, so it can't be altered
        # without breaking the signature. Reject a stale/future-dated envelope to
        # bound how long a captured one stays replayable.
        created = _parse_iso_epoch(envelope.get("created_at"))
        now = self._wall()
        if created is None or abs(now - created) > self.max_age:
            return {"applied": False,
                    "reason": "envelope is stale or future-dated", "result": None}
        if not self.limiter.allow(origin):
            return {"applied": False, "reason": f"rate limited (peer {origin})",
                    "result": None}
        # Replay: reject a second sighting of this signature within the window.
        # The `to` check only stops cross-peer replay; this stops a captured
        # envelope being replayed at this same peer (and dedups at-least-once
        # redeliveries — effectively-once). Checked AFTER the rate limiter and
        # recorded only here, so a rate-limited (dropped) message isn't recorded
        # and its legitimate retry still gets through once the bucket refills.
        if self._replay_seen(str(envelope.get("sig") or ""), now):
            return {"applied": False, "reason": "replayed envelope", "result": None}
        msg = FedMessage(
            channel=f"fed:{origin}",
            user_id=str(user_id)[:MAX_USER_ID_CHARS],
            text=str(text)[:MAX_TEXT_CHARS],
        )
        result = self.handler(msg)
        return {"applied": True, "reason": "ok", "result": result}

    def apply_many(self, envelopes: Iterable[object]) -> list[dict]:
        """Apply a bounded batch from any injected receive iterable."""
        out = []
        for i, env in enumerate(envelopes):
            if i >= _MAX_BATCH:
                log.warning("channel federation: batch truncated at %d", _MAX_BATCH)
                break
            out.append(self.apply(env))
        return out


__all__ = [
    "SCHEMA",
    "MAX_TEXT_CHARS",
    "DEFAULT_QUEUE_MAX",
    "DEFAULT_RATE_PER_MIN",
    "pseudonymize",
    "make_envelope",
    "OutboundQueue",
    "enqueue",
    "flush",
    "TokenBucket",
    "default_limiter",
    "FedMessage",
    "InboundApplier",
]
