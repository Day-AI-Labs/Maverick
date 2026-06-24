"""Governed retirement of an AI system/component -- the far end of the lifecycle.

ISO/IEC 42001 A.6.2 spans the whole AI system life cycle, and the one stage the
rest of this codebase did not yet close is *retirement*: the deliberate,
recorded decommissioning of a system, model role, or learned capability that is
no longer fit for use. Promotion is governed (``learning_rollout``); retirement
must be too, or a system can simply stop being used with no provable end-of-life.

This module makes retirement a first-class, audited act:

  - It records a signed ``AI_SYSTEM_RETIRED`` audit row (who decided, why, and
    what happens to the data) so the Operating Record shows the end-of-life the
    same way it shows learning promotions.
  - It honours an explicit *data disposition* -- ``retain`` / ``archive`` /
    ``erase`` -- so retirement and data lifecycle are decided together.

The pure orchestration (:func:`retire_system`) is deterministic and offline-
tested with injected archive/dispose/record/clock callables; :func:`retire_system_live`
wires the real signed audit row and (for ``archive``) a learning-state snapshot.
Invoked deliberately by an operator -- nothing auto-retires, so the kernel is
unchanged out of the box, exactly like ``learning_rollout``.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

# What happens to the retired system's data when it is decommissioned.
DISPOSITIONS = ("retain", "archive", "erase")


@dataclass
class RetirementRecord:
    """The outcome of one retirement: what was retired, why, and its disposition."""

    system_id: str
    reason: str
    decided_by: str
    data_disposition: str
    ts: float | None = None
    archived: bool = False
    erased: bool = False
    recorded: bool = False
    notes: str = ""


def retire_system(system_id: str, *, reason: str, decided_by: str,
                  data_disposition: str = "archive",
                  archive: Callable[[str], None] | None = None,
                  dispose: Callable[[str], None] | None = None,
                  record_event: Callable[[RetirementRecord], bool] | None = None,
                  now: Callable[[], float] | None = None) -> RetirementRecord:
    """Retire ``system_id`` deliberately, in order, fail-safe. Pure orchestration.

    Steps, each guarded so a failing side-effect degrades the record rather than
    raising a half-finished retirement:

      1. ``archive(system_id)``  -- when disposition is ``archive`` (snapshot the
         state so a retired system is recoverable for audit/rollback).
      2. ``dispose(system_id)``  -- when disposition is ``erase`` (irreversibly
         remove the system's data; the audit row of the act remains).
      3. ``record_event(record)`` -- append the signed ``AI_SYSTEM_RETIRED`` row.

    ``data_disposition`` must be one of :data:`DISPOSITIONS`; an unknown value is
    coerced to ``archive`` (the safe default -- never silently ``erase``) and
    noted. All callables are injected so this is deterministic and offline-tested;
    :func:`retire_system_live` supplies the real ones.
    """
    disposition = data_disposition if data_disposition in DISPOSITIONS else "archive"
    notes = ""
    if disposition != data_disposition:
        notes = f"unknown disposition {data_disposition!r} coerced to 'archive'"

    ts = None
    if now is not None:
        try:
            ts = now()
        except Exception:  # a broken clock must not block retirement
            ts = None

    record = RetirementRecord(
        system_id=system_id, reason=reason, decided_by=decided_by,
        data_disposition=disposition, ts=ts, notes=notes,
    )

    if disposition == "archive" and archive is not None:
        try:
            archive(system_id)
            record.archived = True
        except Exception as e:
            log.warning("retire: archive of %r failed (%s)", system_id, e)
            record.notes = (record.notes + "; " if record.notes else "") + f"archive failed: {e}"

    if disposition == "erase" and dispose is not None:
        try:
            dispose(system_id)
            record.erased = True
        except Exception as e:
            log.warning("retire: disposal of %r failed (%s)", system_id, e)
            record.notes = (record.notes + "; " if record.notes else "") + f"erase failed: {e}"

    if record_event is not None:
        try:
            record.recorded = bool(record_event(record))
        except Exception as e:
            log.warning("retire: audit record for %r failed (%s)", system_id, e)

    return record


def retire_system_live(system_id: str, *, reason: str, decided_by: str,
                       data_disposition: str = "archive") -> RetirementRecord:  # pragma: no cover -- touches learned state / audit sink
    """Live retirement: wire the real signed audit row and (for ``archive``) a
    learning-state snapshot, then run the governed :func:`retire_system` flow.

    Fail-safe: a missing audit sink or snapshot helper degrades the record (the
    relevant flag stays False) but never raises -- retiring a system must not be
    able to crash the host doing it.
    """
    import time

    def archive(_sid: str) -> None:
        from . import dreaming
        dreaming.snapshot_learning_state()

    def dispose(_sid: str) -> None:
        # Disposal of system-specific data is deployment-specific; the audited
        # act is recorded regardless. Operators wire concrete erasure (e.g.
        # maverick.audit.erase / world-model deletion) per their data map.
        log.info("retire: disposition=erase for %r -- wire deployment-specific erasure", _sid)

    def record_event(rec: RetirementRecord) -> bool:
        from .audit import EventKind, record
        return record(
            EventKind.AI_SYSTEM_RETIRED, agent="retirement",
            system_id=rec.system_id, reason=rec.reason, decided_by=rec.decided_by,
            data_disposition=rec.data_disposition, archived=rec.archived,
        )

    return retire_system(
        system_id, reason=reason, decided_by=decided_by,
        data_disposition=data_disposition,
        archive=archive, dispose=dispose, record_event=record_event, now=time.time,
    )


__all__ = ["RetirementRecord", "DISPOSITIONS", "retire_system", "retire_system_live"]
