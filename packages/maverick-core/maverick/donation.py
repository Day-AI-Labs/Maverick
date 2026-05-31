"""Opt-in trajectory donation — the Tesla data-engine analog.

Karpathy SOTA-review item: schema v6 has the right shape for episode
collection, but no selection function. The flywheel only works if the
upload is:

1. **Opt-in, default OFF.** ``[telemetry] donate_trajectories = true``
   in ``~/.maverick/config.toml`` (also surfaced in the installer
   wizard) is the only way to enable it. No env-var shortcut.
2. **Client-side scrubbed.** Every text field passes through the
   secret-scrubber + a PII-redaction step BEFORE landing in the
   outbox. The user can inspect ``~/.maverick/outbox/`` before
   anything is sent.
3. **Metadata-only by default.** Tuple is
   ``(task_brief_hash, action_sequence, terminal_reward, model_id,
   tool_subset, disagreement_entropy)``. NO raw text unless the user
   ALSO opts into ``donate_text = true``.
4. **Selective.** Only trajectories where
   ``disagreement_high AND outcome == 'success'`` are written -- the
   cases where the swarm learned something the solo agent couldn't.
   Everything else is noise.

The outbox is a local directory; the actual upload (HTTP POST to a
collection endpoint) is a follow-up commit and will only fire when
the user explicitly runs ``maverick donate-upload``. This commit gets
the data in the right shape and on disk; it does NOT phone home.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .secrets import scrub

log = logging.getLogger(__name__)


DEFAULT_OUTBOX = Path.home() / ".maverick" / "outbox"


@dataclass
class TrajectoryRecord:
    """One donated trajectory.

    The hashed task brief identifies a task family (same prompt → same
    hash) for aggregation across users without exposing user text.
    Action sequence is tool names + JSON-shape only -- no argument
    values, no return values.
    """
    schema_version: int = 1
    ts: float = field(default_factory=time.time)
    task_brief_hash: str = ""
    task_brief_text: str | None = None  # only when donate_text=true
    model_id: str = ""
    tools_used: list[str] = field(default_factory=list)
    action_sequence: list[str] = field(default_factory=list)
    outcome: str = ""              # success / failure / blocked / etc
    reward: float = 0.0             # 1.0 on accept, 0.0 on reject, else verifier confidence
    verifier_confidence: float = 0.0
    verifier_critique: str = ""
    disagreement_entropy: float = 0.0
    wall_seconds: float = 0.0
    cost_dollars: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


def _donations_enabled() -> bool:
    """Single source of truth for the opt-in toggle."""
    try:
        from .config import load_config
        cfg = load_config()
        return bool(cfg.get("telemetry", {}).get("donate_trajectories", False))
    except Exception:
        return False


def _text_donations_enabled() -> bool:
    try:
        from .config import load_config
        cfg = load_config()
        tel = cfg.get("telemetry", {})
        return bool(
            tel.get("donate_trajectories", False)
            and tel.get("donate_text", False)
        )
    except Exception:
        return False


def hash_brief(brief: str) -> str:
    """Stable identifier for a task brief without revealing its text."""
    return hashlib.sha256(brief.strip().encode("utf-8")).hexdigest()[:16]


def should_donate(
    outcome: str,
    verifier_confidence: float,
    disagreement_entropy: float,
    *,
    min_entropy: float = 0.5,
    min_confidence: float = 0.75,
) -> bool:
    """Selection: only the trajectories the model can learn from.

    Gold rows are: high disagreement (the swarm actually explored
    multiple branches) AND high verifier confidence on the chosen
    branch (we know the right answer was eventually reached) AND
    outcome=success (the trajectory closed cleanly).
    """
    if outcome != "success":
        return False
    if verifier_confidence < min_confidence:
        return False
    if disagreement_entropy < min_entropy:
        return False
    return True


def write_record(
    record: TrajectoryRecord,
    *,
    outbox: Path | None = None,
) -> Path | None:
    """Persist a record to the local outbox, with scrubbing.

    Returns the written path, or None if donations are disabled OR the
    record doesn't pass the selection gate. Never raises -- a bug in
    the donor must not affect the actual goal execution.
    """
    if not _donations_enabled():
        return None
    if not should_donate(
        record.outcome, record.verifier_confidence, record.disagreement_entropy,
    ):
        return None

    # Strip text fields unless the user opted into that too.
    if not _text_donations_enabled():
        record.task_brief_text = None

    # Scrub every text field that could carry secrets -- including list-of-str
    # fields (tools_used / action_sequence), which the str-only loop skipped,
    # breaking the module's "every text field is scrubbed" contract.
    payload = asdict(record)
    for k, v in list(payload.items()):
        if isinstance(v, str):
            payload[k] = scrub(v)
        elif isinstance(v, list):
            payload[k] = [scrub(x) if isinstance(x, str) else x for x in v]

    try:
        out_dir = outbox or DEFAULT_OUTBOX
        out_dir.mkdir(parents=True, exist_ok=True)
        # Trajectory records carry prompt/result text; keep the outbox and
        # files owner-only (the default umask often leaves them
        # world-readable on servers).
        try:
            out_dir.chmod(0o700)
        except OSError:
            pass
        fname = f"{record.ts:.0f}-{record.task_brief_hash}.json"
        path = out_dir / fname
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return path
    except Exception as e:  # pragma: no cover
        log.warning("trajectory donation write failed: %s", e)
        return None


def list_pending(outbox: Path | None = None) -> list[Path]:
    """Return the outbox files awaiting upload, for `maverick donate-status`."""
    out_dir = outbox or DEFAULT_OUTBOX
    if not out_dir.exists():
        return []
    return sorted(out_dir.glob("*.json"))


def clear_outbox(outbox: Path | None = None) -> int:
    """Delete every pending record. Returns count removed."""
    out_dir = outbox or DEFAULT_OUTBOX
    if not out_dir.exists():
        return 0
    n = 0
    for p in out_dir.glob("*.json"):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n
