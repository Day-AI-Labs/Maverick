"""Cryptographic budget receipts: tamper-evident spend records
(roadmap: 2028 H1 safety).

A spend number in a mutable JSON file is an assertion, not evidence. When an
agent platform bills (or is audited on) what its runs cost, the operator
needs receipts that (a) can't be quietly edited after the fact and (b) can't
be quietly *deleted* — an over-budget run that simply vanishes from the
ledger is the same lie as one whose total was shaved.

So a receipt is:

* the run's spend gathered from the world model's episode rows
  (:class:`maverick.world_model.EpisodeSpend`: ``cost_dollars`` /
  ``input_tokens`` / ``output_tokens`` / ``tool_calls`` per episode of the
  goal), plus the deployment's ``[budget]`` caps for context;
* serialized as **canonical JSON** (sorted keys, fixed separators — byte
  stability is what makes a MAC meaningful);
* **HMAC-SHA256-signed** with a deployment receipt key (``[safety]
  receipt_key`` / env ``MAVERICK_RECEIPT_KEY``, env wins). No key configured
  -> :func:`mint` refuses with :class:`ReceiptKeyMissing` — an unsigned
  receipt is worthless, and silently minting one would teach operators to
  trust paper;
* **hash-chained**: each receipt's signed payload embeds
  ``prev_receipt_hash`` (sha256 of the previous receipt line in
  ``data_dir("budget_receipts.jsonl")``, ``None`` for the genesis receipt),
  and is appended to that file (created 0600, append-only). Deleting or
  reordering a line breaks the chain at a verifiable spot.

HMAC (symmetric) rather than Ed25519: the verifier and the minter are the
same deployment boundary here, stdlib ``hmac``/``hashlib`` need no extra
dependency, and the audit subsystem's asymmetric signing stays available for
receipts that must cross trust boundaries later.

Pure library, default OFF (nothing mints unless called; no key, no mint).
The clock is injectable for tests. Fail-soft only in the *config* reads —
verification itself never fails soft: a bad signature is ``INVALID``, a
malformed blob is ``MALFORMED``, loudly.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .paths import data_dir

VALID = "VALID"
INVALID = "INVALID"
MALFORMED = "MALFORMED"

_ALG = "HMAC-SHA256"


class ReceiptKeyMissing(RuntimeError):
    """No receipt key is configured; minting unsigned receipts is refused."""

    def __init__(self) -> None:
        super().__init__(
            "budget receipts require a deployment receipt key: set "
            "MAVERICK_RECEIPT_KEY or [safety] receipt_key in "
            "~/.maverick/config.toml. Refusing to mint an unsigned receipt — "
            "it would prove nothing."
        )


@dataclass(frozen=True)
class ChainReport:
    """Outcome of :func:`verify_chain`. ``broken_at`` is the 0-based line
    index of the first bad receipt (``None`` when the chain holds)."""

    count: int
    broken_at: int | None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.broken_at is None


def receipts_path() -> Path:
    """The deployment's append-only receipt chain (tenant-aware data dir)."""
    return data_dir("budget_receipts.jsonl")


def resolve_key(key: str | None = None) -> str:
    """The receipt key: explicit arg > ``MAVERICK_RECEIPT_KEY`` > ``[safety]
    receipt_key``. Raises :class:`ReceiptKeyMissing` when absent/blank."""
    if key:
        return key
    env = os.environ.get("MAVERICK_RECEIPT_KEY", "").strip()
    if env:
        return env
    try:
        from .config import load_config
        cfg_key = str(((load_config() or {}).get("safety") or {}).get("receipt_key") or "")
    except Exception:
        cfg_key = ""
    if cfg_key.strip():
        return cfg_key.strip()
    raise ReceiptKeyMissing


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _sign(payload: dict, key: str) -> str:
    return hmac.new(key.encode("utf-8"), _canonical(payload),
                    hashlib.sha256).hexdigest()


def _receipt_hash(line: str) -> str:
    """sha256 of a stored receipt line — the chain link the next receipt embeds."""
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()


def _last_line(path: Path) -> str | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    return lines[-1] if lines else None


def _budget_caps() -> dict:
    """The deployment's ``[budget]`` caps, for receipt context. Fail-soft."""
    try:
        from .config import get_budget_overrides
        caps = get_budget_overrides() or {}
        return {str(k): v for k, v in caps.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)}
    except Exception:
        return {}


def mint(
    world,
    goal_id: int,
    key: str | None = None,
    *,
    path: str | Path | None = None,
    clock: Callable[[], float] = time.time,
) -> str:
    """Mint, append, and return the signed receipt line for ``goal_id``.

    Gathers every episode of the goal from ``world.list_episodes(goal_id=...)``
    and totals the :class:`~maverick.world_model.EpisodeSpend` fields.
    ``started_at`` is the earliest episode start, ``ended_at`` the latest
    episode end (``None`` if no episode finished). The receipt is appended to
    the deployment chain (``path`` defaults to :func:`receipts_path`), linked
    to the previous receipt by hash, and returned as the exact stored line —
    pass it straight to :func:`verify`.
    """
    real_key = resolve_key(key)
    episodes = list(world.list_episodes(limit=100000, goal_id=goal_id))
    starts = [e.started_at for e in episodes]
    ends = [e.ended_at for e in episodes if e.ended_at is not None]
    chain_path = Path(path) if path is not None else receipts_path()
    prev_line = _last_line(chain_path)
    payload = {
        "goal_id": int(goal_id),
        "total_dollars": round(sum(e.cost_dollars for e in episodes), 6),
        "in_tokens": sum(e.input_tokens for e in episodes),
        "out_tokens": sum(e.output_tokens for e in episodes),
        "tool_calls": sum(e.tool_calls for e in episodes),
        "episodes": len(episodes),
        "started_at": min(starts) if starts else None,
        "ended_at": max(ends) if ends else None,
        "budget_caps": _budget_caps(),
        "minted_at": float(clock()),
        "prev_receipt_hash": _receipt_hash(prev_line) if prev_line else None,
    }
    receipt = {"alg": _ALG, "payload": payload, "sig": _sign(payload, real_key)}
    line = json.dumps(receipt, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    chain_path.parent.mkdir(parents=True, exist_ok=True)
    # Append-only, created 0600: the chain is the tamper-evidence, the mode
    # keeps other local users from reading spend data.
    fd = os.open(chain_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode("utf-8") + b"\n")
    finally:
        os.close(fd)
    return line


def verify(receipt_json: str, key: str) -> str:
    """Check one receipt: :data:`VALID`, :data:`INVALID` (bad signature), or
    :data:`MALFORMED` (not a receipt-shaped JSON object at all)."""
    try:
        receipt = json.loads(receipt_json)
    except (ValueError, TypeError):
        return MALFORMED
    if not isinstance(receipt, dict):
        return MALFORMED
    payload, sig = receipt.get("payload"), receipt.get("sig")
    if not isinstance(payload, dict) or not isinstance(sig, str):
        return MALFORMED
    expected = _sign(payload, key)
    return VALID if hmac.compare_digest(expected, sig) else INVALID


def verify_chain(path: str | Path | None = None, key: str | None = None) -> ChainReport:
    """Walk the receipt chain: every signature must verify AND every
    ``prev_receipt_hash`` must equal the hash of the line before it.

    Returns the first break (signature failure, malformed line, or a hash
    mismatch — i.e. an edited, deleted, or reordered receipt). An absent
    file is an intact empty chain.
    """
    real_key = resolve_key(key)
    chain_path = Path(path) if path is not None else receipts_path()
    try:
        raw = chain_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ChainReport(count=0, broken_at=None)
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    prev_hash: str | None = None
    for i, line in enumerate(lines):
        status = verify(line, real_key)
        if status != VALID:
            return ChainReport(count=len(lines), broken_at=i,
                               reason=f"receipt {i} is {status}")
        embedded = json.loads(line)["payload"].get("prev_receipt_hash")
        if embedded != prev_hash:
            return ChainReport(count=len(lines), broken_at=i,
                               reason=f"receipt {i} chain link mismatch "
                                      "(deleted/reordered predecessor?)")
        prev_hash = _receipt_hash(line)
    return ChainReport(count=len(lines), broken_at=None)


def render(receipt_json: str) -> str:
    """CLI-style, human-readable view of one receipt line."""
    try:
        receipt = json.loads(receipt_json)
        p = receipt["payload"]
    except (ValueError, TypeError, KeyError):
        return "budget receipt: MALFORMED"
    caps = p.get("budget_caps") or {}
    caps_str = ", ".join(f"{k}={v}" for k, v in sorted(caps.items())) or "none"
    prev = p.get("prev_receipt_hash")
    return (
        f"budget receipt  goal={p.get('goal_id')}  ${p.get('total_dollars', 0):.4f}\n"
        f"  tokens in={p.get('in_tokens', 0)} out={p.get('out_tokens', 0)}  "
        f"tool_calls={p.get('tool_calls', 0)}  episodes={p.get('episodes', 0)}\n"
        f"  window {p.get('started_at')} -> {p.get('ended_at')}\n"
        f"  caps: {caps_str}\n"
        f"  chain: prev={prev[:16] + '...' if prev else '(genesis)'}  "
        f"sig={receipt.get('sig', '')[:16]}... ({receipt.get('alg')})"
    )


__all__ = [
    "VALID", "INVALID", "MALFORMED",
    "ReceiptKeyMissing", "ChainReport",
    "mint", "verify", "verify_chain", "render",
    "receipts_path", "resolve_key",
]
