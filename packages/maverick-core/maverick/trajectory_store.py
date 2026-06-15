"""Governed trajectory capture -- the data foundation for self-improvement.

Nothing downstream can *learn* without a record of what the agents actually
did. This is that record: a per-tenant, consent-gated, secret-redacted,
append-only store of agent steps (role, tool, outcome, error, verifier
confidence, process-reward signal). It is the raw material the verifier/policy
training rungs consume and the substrate the compounding-metric reads.

Posture (kernel rule 1): OFF by default. Capture only happens when
``[self_improvement] capture`` (env ``MAVERICK_TRAJECTORY_CAPTURE``) is set, so a
default deployment records nothing. Every text field is run through
``secrets.scrub`` before it touches disk (a trajectory outlives the run and must
not become a credential leak). Writes are atomic-append, 0600, tenant-scoped via
``paths.data_dir``, and bounded (oldest rows roll off). Fail-open: a capture
error is logged and swallowed, never raised into a run.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_MAX_ROWS = 50_000  # bounded; oldest roll off


def enabled() -> bool:
    """Whether trajectory capture is on. OFF by default, fail-open."""
    if os.environ.get("MAVERICK_TRAJECTORY_CAPTURE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return True
    try:
        from .config import get_self_improvement
        return bool(get_self_improvement().get("capture", False))
    except Exception:  # pragma: no cover -- config never blocks a run
        return False


def _scrub(text: str | None) -> str:
    if not text:
        return ""
    try:
        from .secrets import scrub
        return scrub(str(text))
    except Exception:  # pragma: no cover -- never block capture on a scrub error
        return ""


@dataclass
class TrajectoryStep:
    ts: float
    goal_id: int
    episode_id: int
    step: int
    role: str
    tool: str = ""
    tool_succeeded: bool | None = None
    is_final: bool = False
    error: str = ""
    verifier_confidence: float | None = None
    promise: float | None = None
    progress: float | None = None
    domain: str = ""
    # Decision-DAG edge + terminal label, for counterfactual credit
    # (maverick.promotion_effect). ``parent_step`` is the step this one descends
    # from (None at a root); ``outcome`` is the episode's terminal task outcome in
    # [0,1], carried on the final step. Both optional and absent in old rows.
    parent_step: int | None = None
    outcome: float | None = None

    def redacted(self) -> TrajectoryStep:
        """A copy safe to persist: scrub free-text fields."""
        return TrajectoryStep(
            ts=self.ts, goal_id=self.goal_id, episode_id=self.episode_id,
            step=self.step, role=_scrub(self.role)[:64], tool=_scrub(self.tool)[:64],
            tool_succeeded=self.tool_succeeded, is_final=self.is_final,
            error=_scrub(self.error)[:500], verifier_confidence=self.verifier_confidence,
            promise=self.promise, progress=self.progress, domain=_scrub(self.domain)[:64],
            parent_step=self.parent_step, outcome=self.outcome,
        )


@dataclass
class TrajectoryStore:
    path: Path | None = None
    max_rows: int = _MAX_ROWS
    _lock: threading.Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self._lock is None:
            self._lock = threading.Lock()

    def record(self, step: TrajectoryStep) -> bool:
        """Append one redacted step. Returns True on success; never raises."""
        if self.path is None:
            return False
        try:
            line = json.dumps(asdict(step.redacted()), sort_keys=True)
            with self._lock:
                p = Path(self.path)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(os.open(p, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600),
                          "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                self._maybe_rotate(p)
            return True
        except Exception:  # pragma: no cover -- capture is best-effort
            log.debug("trajectory capture failed", exc_info=True)
            return False

    def _maybe_rotate(self, p: Path) -> None:
        # Cheap bound: when the file exceeds the cap, keep the newest max_rows.
        try:
            with open(p, encoding="utf-8") as fh:
                lines = fh.readlines()
            if len(lines) <= self.max_rows:
                return
            kept = lines[-self.max_rows:]
            tmp = p.with_suffix(".tmp")
            tmp.write_text("".join(kept), encoding="utf-8")
            os.replace(tmp, p)
            os.chmod(p, 0o600)
        except Exception:  # pragma: no cover
            pass

    def iter_steps(self, *, goal_id: int | None = None, limit: int = 10_000):
        """Yield stored steps (optionally for one goal), newest last."""
        if self.path is None or not Path(self.path).exists():
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:  # pragma: no cover
            return
        for raw in lines[-limit:]:
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if goal_id is not None and d.get("goal_id") != goal_id:
                continue
            yield TrajectoryStep(**{k: d.get(k) for k in TrajectoryStep.__dataclass_fields__})

    def count(self) -> int:
        if self.path is None or not Path(self.path).exists():
            return 0
        try:
            with open(self.path, encoding="utf-8") as fh:
                return sum(1 for _ in fh)
        except OSError:  # pragma: no cover
            return 0


_shared: dict[Path, TrajectoryStore] = {}
_shared_lock = threading.Lock()


def shared() -> TrajectoryStore:
    from .paths import data_dir

    path = data_dir("trajectories.ndjson")
    with _shared_lock:
        store = _shared.get(path)
        if store is None:
            store = TrajectoryStore(path=path)
            _shared[path] = store
        return store


def reset_shared() -> None:
    with _shared_lock:
        _shared.clear()


def capture_step(step: TrajectoryStep, *, store: TrajectoryStore | None = None) -> bool:
    """Opt-in entry point. No-op (returns False) unless capture is enabled."""
    if not enabled():
        return False
    try:
        return (store or shared()).record(step)
    except Exception:  # pragma: no cover -- never block a run
        return False


__all__ = [
    "TrajectoryStep", "TrajectoryStore",
    "enabled", "shared", "reset_shared", "capture_step",
]
