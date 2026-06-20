"""Skill usage tracking + decay.

The distill-time quality gate judges a skill by the run that CREATED it.
This module judges a skill by how it PERFORMS once in circulation: every
time a skill is recalled into a run we record a use, and when that run
finishes we record the outcome against the skills it used. A skill that's
repeatedly recalled but rides along with failures loses rank (decay); one
that rarely helps and never wins can be evicted. This closes the learning
loop — the library curates itself instead of only growing.

Storage: ``~/.maverick/skill_stats.json`` (chmod 600), a flat map of
``name -> {uses, wins, losses, last_used}``. Reads/writes go through a
process lock and are fully fail-safe — stats are an optimization, never a
correctness dependency, so any I/O error degrades to "no signal" (neutral
weight) and never blocks a run.

All recording is opt-in-friendly: disable the decay multiplier with
``MAVERICK_SKILL_DECAY=0`` and ranking falls back to relevance only.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .paths import data_dir

log = logging.getLogger(__name__)

DEFAULT_PATH = data_dir("skill_stats.json")
_lock = threading.Lock()


@dataclass
class SkillStat:
    uses: int = 0
    wins: int = 0
    losses: int = 0
    last_used: float = 0.0


def _enabled() -> bool:
    return os.environ.get("MAVERICK_SKILL_DECAY", "1") != "0"


def _resolve(path: Path | None) -> Path:
    """Resolve the stats path, reading the module attribute at CALL time.

    Binding ``DEFAULT_PATH`` as a function default would freeze it at import
    time, so a test that monkeypatches ``skill_stats.DEFAULT_PATH`` (or a
    future per-profile override) wouldn't take effect. Callers pass None to
    mean "use the current default."
    """
    if path is not None:
        return path
    # Item-30 isolation: an ACTIVE tenant gets its own stats store. The
    # module-attr lookup below stays last so tests monkeypatching
    # DEFAULT_PATH keep working in the single-tenant layout.
    try:
        from .paths import current_tenant, data_dir
        if current_tenant():
            return data_dir("skill_stats.json")
    except Exception:  # pragma: no cover -- isolation never blocks resolution
        pass
    return DEFAULT_PATH


def _load(path: Path) -> dict[str, SkillStat]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, SkillStat] = {}
    if not isinstance(raw, dict):
        return {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        try:
            out[name] = SkillStat(
                uses=int(entry.get("uses", 0)),
                wins=int(entry.get("wins", 0)),
                losses=int(entry.get("losses", 0)),
                last_used=float(entry.get("last_used", 0.0)),
            )
        except (TypeError, ValueError):
            continue
    return out


def _save(stats: dict[str, SkillStat], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({k: asdict(v) for k, v in stats.items()}),
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def record_use(names: list[str], path: Path | None = None) -> None:
    """Mark that ``names`` were recalled into a run. Fail-safe no-op on error."""
    if not _enabled() or not names:
        return
    path = _resolve(path)
    with _lock:
        try:
            stats = _load(path)
            now = time.time()
            for n in names:
                st = stats.get(n) or SkillStat()
                st.uses += 1
                st.last_used = now
                stats[n] = st
            _save(stats, path)
        except OSError as e:  # pragma: no cover
            log.debug("skill_stats record_use failed: %s", e)


def record_outcome(
    names: list[str], *, success: bool, path: Path | None = None,
) -> None:
    """Attribute a run's outcome to the skills it used. Fail-safe."""
    if not _enabled() or not names:
        return
    path = _resolve(path)
    with _lock:
        try:
            stats = _load(path)
            for n in names:
                st = stats.get(n) or SkillStat()
                if success:
                    st.wins += 1
                else:
                    st.losses += 1
                stats[n] = st
            _save(stats, path)
        except OSError as e:  # pragma: no cover
            log.debug("skill_stats record_outcome failed: %s", e)


def _weight_from_stat(
    st: SkillStat | None, min_uses: int, floor: float,
) -> float:
    """Pure win-rate → multiplier in [floor, 1.0]. Shared by the single and
    batch accessors so the decay curve is defined in exactly one place."""
    if st is None or st.uses < min_uses:
        return 1.0
    decided = st.wins + st.losses
    if decided == 0:
        return 1.0
    return floor + (1.0 - floor) * (st.wins / decided)


def decay_weight(
    name: str,
    *,
    path: Path | None = None,
    min_uses: int = 3,
    floor: float = 0.5,
) -> float:
    """Track-record multiplier in [floor, 1.0] for a skill by name.

    Neutral (1.0) until a skill has been used ``min_uses`` times — we don't
    punish a skill before it's had a fair chance. After that, the weight is
    ``floor + (1-floor) * win_rate`` where win_rate = wins / (wins+losses).
    A skill that always rides along with successful runs stays at 1.0; one
    that consistently rides along with failures decays toward ``floor`` (it
    yields to alternatives but is never fully silenced — relevance can still
    surface it). Returns 1.0 on any error or when decay is disabled.
    """
    if not _enabled():
        return 1.0
    try:
        with _lock:
            stats = _load(_resolve(path))
        return _weight_from_stat(stats.get(name), min_uses, floor)
    except Exception:  # pragma: no cover -- stats never block recall
        return 1.0


def decay_weights(
    names: list[str],
    *,
    path: Path | None = None,
    min_uses: int = 3,
    floor: float = 0.5,
) -> dict[str, float]:
    """Batch ``decay_weight``: one file read for many names.

    Skill retrieval weights every candidate BEFORE truncating to top-N, so
    the per-name accessor would re-read the stats file once per candidate.
    This loads it once. Missing names and any error degrade to neutral 1.0,
    so callers never have to special-case a partial result.
    """
    if not _enabled():
        return dict.fromkeys(names, 1.0)
    try:
        with _lock:
            stats = _load(_resolve(path))
    except Exception:  # pragma: no cover -- stats never block recall
        return dict.fromkeys(names, 1.0)
    return {n: _weight_from_stat(stats.get(n), min_uses, floor) for n in names}


def evictable(
    *,
    path: Path | None = None,
    min_uses: int = 5,
    max_win_rate: float = 0.2,
) -> list[str]:
    """Names of skills that have had a fair trial and rarely help.

    A skill is evictable when it's been used at least ``min_uses`` times,
    has a decided outcome, and its win rate is at or below ``max_win_rate``.
    Callers (e.g. a maintenance command) decide whether to actually delete;
    this function only identifies candidates and never mutates state.
    """
    try:
        with _lock:
            stats = _load(_resolve(path))
    except Exception:  # pragma: no cover
        return []
    out: list[str] = []
    for name, st in stats.items():
        decided = st.wins + st.losses
        if st.uses >= min_uses and decided > 0 and (st.wins / decided) <= max_win_rate:
            out.append(name)
    return out


def get(name: str, path: Path | None = None) -> SkillStat | None:
    """Return the stored stat for ``name``, or None."""
    try:
        with _lock:
            return _load(_resolve(path)).get(name)
    except Exception:  # pragma: no cover
        return None


__all__ = [
    "SkillStat",
    "DEFAULT_PATH",
    "record_use",
    "record_outcome",
    "decay_weight",
    "decay_weights",
    "evictable",
    "get",
]
