"""Failure-mode telemetry (opt-in) (roadmap: 2027 H2 performance).

When runs fail, *how* they fail is the signal worth having: is it mostly budget
caps, provider auth, timeouts, the shield, sandbox errors? This records a
canonical **failure mode** per failed run to a local JSONL sink, so an operator
can see the distribution and fix the dominant cause instead of guessing.

Local-first and **opt-in** (``[telemetry] failure_modes`` / env
``MAVERICK_FAILURE_TELEMETRY=1``), default OFF — ``record`` is a cheap
``enabled()`` check and returns immediately when unconfigured, so the
orchestrator's best-effort tee costs nothing on a run that didn't ask for it.
No mandatory egress: the JSONL stays on disk; ``summarize`` / ``maverick
failures`` read it back.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# Canonical failure modes (anything else normalizes to "error").
MODES = ("budget", "timeout", "network", "auth", "shield", "sandbox",
         "cancelled", "error")


def enabled() -> bool:
    if os.environ.get("MAVERICK_FAILURE_TELEMETRY", "").strip().lower() in {
            "1", "true", "yes", "on"}:
        return True
    try:
        from .config import load_config
        return bool(((load_config() or {}).get("telemetry") or {})
                    .get("failure_modes", False))
    except Exception:  # pragma: no cover -- config never blocks a run
        return False


def classify_exception(exc: BaseException) -> str:
    """Map an exception to a canonical failure mode."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "budget" in name or "budget" in msg:
        return "budget"
    if "timeout" in name or "timed out" in msg:
        return "timeout"
    if "auth" in name or "unauthor" in msg or "api key" in msg or "401" in msg:
        return "auth"
    if "connection" in name or "network" in msg or name.startswith("connect"):
        return "network"
    if "shield" in name or "shield" in msg:
        return "shield"
    if "sandbox" in name or ("sandbox" in msg and "exec" in msg):
        return "sandbox"
    if "cancel" in name or "cancelled" in msg:
        return "cancelled"
    return "error"


def _path() -> Path:
    from .paths import data_dir
    return data_dir("failure_modes.jsonl")


def record(mode: str, *, goal_id=None, detail: str = "",
           now: float | None = None, path=None) -> bool:
    """Append one failure-mode record (no-op + False when telemetry is off)."""
    if not enabled():
        return False
    try:
        p = Path(path) if path is not None else _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": now if now is not None else time.time(),
            "mode": mode if mode in MODES else "error",
            "goal_id": goal_id,
            "detail": str(detail)[:200],
        }
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        return True
    except Exception:  # pragma: no cover -- telemetry never breaks a run
        return False


def record_failure(exc_or_mode, *, goal_id=None, detail: str = "", **kw) -> bool:
    """Record from an exception (classified) or an explicit mode string."""
    if isinstance(exc_or_mode, str):
        mode = exc_or_mode if exc_or_mode in MODES else "error"
    else:
        mode = classify_exception(exc_or_mode)
        detail = detail or str(exc_or_mode)
    return record(mode, goal_id=goal_id, detail=detail, **kw)


def summarize(path=None) -> dict:
    """Failure-mode distribution from the recorded sink."""
    p = Path(path) if path is not None else _path()
    counts: dict[str, int] = {}
    total = 0
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {"total": 0, "by_mode": {}}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        m = rec.get("mode", "error")
        counts[m] = counts.get(m, 0) + 1
        total += 1
    return {"total": total,
            "by_mode": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))}


__all__ = ["enabled", "classify_exception", "record", "record_failure",
           "summarize", "MODES"]
