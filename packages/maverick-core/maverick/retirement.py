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
from dataclasses import dataclass, field

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
    # Concrete disposal details (e.g. counts of erased world facts / audit
    # events), populated from the ``dispose`` callable's return value.
    disposal_detail: dict = field(default_factory=dict)


def retire_system(system_id: str, *, reason: str, decided_by: str,
                  data_disposition: str = "archive",
                  archive: Callable[[str], None] | None = None,
                  dispose: Callable[[str], dict | None] | None = None,
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
            details = dispose(system_id)
            record.erased = True
            if isinstance(details, dict):
                record.disposal_detail = dict(details)
        except Exception as e:
            log.warning("retire: disposal of %r failed (%s)", system_id, e)
            record.notes = (record.notes + "; " if record.notes else "") + f"erase failed: {e}"

    if record_event is not None:
        try:
            record.recorded = bool(record_event(record))
        except Exception as e:
            log.warning("retire: audit record for %r failed (%s)", system_id, e)

    return record


def _erase_system_data(system_id: str, erase_scope: dict | None) -> dict:  # pragma: no cover -- deletes real data
    """Concretely erase a retired system's data, gated on an explicit scope.

    The audit and world-model erasure primitives are **subject-scoped** (GDPR
    Art. 17): ``audit.erase.delete_user(channel, user_id)`` and
    ``world.delete_facts_matching(token)`` both key on a subject. Retiring an AI
    *system* therefore erases concrete data only when ``erase_scope`` names the
    subject(s) tied to that system -- e.g. retiring a per-tenant agent and
    removing that tenant's records. Without a scope nothing is deleted (the act
    is still recorded): retirement must never be able to over-delete by guessing
    what "the system's data" is from a bare id. ``erase_scope`` keys:

      - ``audit_subject``: ``(channel, user_id)`` -> ``delete_user`` (audit rows)
      - ``world_subject``: ``token``               -> ``delete_facts_matching``

    Returns a details dict of what was erased, for the audit payload.
    """
    details: dict = {}
    scope = erase_scope or {}

    subject = scope.get("audit_subject")
    if subject:
        try:
            from .audit.erase import delete_user
            channel, user_id = subject
            deleted, scanned = delete_user(str(channel), str(user_id))
            details["audit_events_deleted"] = deleted
            details["audit_events_scanned"] = scanned
        except Exception as e:
            log.warning("retire: audit erase for %r failed (%s)", system_id, e)
            details["audit_erase_error"] = str(e)

    world_subject = scope.get("world_subject")
    if world_subject:
        try:
            from .world_model import open_world
            keys = open_world().delete_facts_matching(str(world_subject))
            details["world_facts_deleted"] = len(keys)
        except Exception as e:
            log.warning("retire: world erase for %r failed (%s)", system_id, e)
            details["world_erase_error"] = str(e)

    if not subject and not world_subject:
        details["note"] = "no erase_scope provided; no subject data deleted"
        log.info("retire: disposition=erase for %r but no erase_scope given", system_id)
    return details


def retire_system_live(system_id: str, *, reason: str, decided_by: str,
                       data_disposition: str = "archive",
                       erase_scope: dict | None = None) -> RetirementRecord:  # pragma: no cover -- touches learned state / audit sink
    """Live retirement: wire the real signed audit row, a learning-state snapshot
    (for ``archive``) and concrete subject-scoped erasure (for ``erase``), then
    run the governed :func:`retire_system` flow.

    ``erase_scope`` (used only when ``data_disposition='erase'``) names the
    subject(s) whose data to delete -- see :func:`_erase_system_data`. Fail-safe:
    a missing audit sink, snapshot helper, or erase target degrades the record
    (the relevant flag/detail reflects it) but never raises -- retiring a system
    must not be able to crash the host doing it.
    """
    import time

    def archive(_sid: str) -> None:
        from . import dreaming
        dreaming.snapshot_learning_state()

    def dispose(sid: str) -> dict:
        return _erase_system_data(sid, erase_scope)

    def record_event(rec: RetirementRecord) -> bool:
        from .audit import EventKind, record
        return record(
            EventKind.AI_SYSTEM_RETIRED, agent="retirement",
            system_id=rec.system_id, reason=rec.reason, decided_by=rec.decided_by,
            data_disposition=rec.data_disposition, archived=rec.archived,
            erased=rec.erased, disposal_detail=rec.disposal_detail,
        )

    return retire_system(
        system_id, reason=reason, decided_by=decided_by,
        data_disposition=data_disposition,
        archive=archive, dispose=dispose, record_event=record_event, now=time.time,
    )


__all__ = ["RetirementRecord", "DISPOSITIONS", "retire_system", "retire_system_live"]
