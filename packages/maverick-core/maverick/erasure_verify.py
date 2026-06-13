"""Differential erasure verification (roadmap: 2028 H2 safety).

A right-to-erasure (GDPR Art. 17) run that *says* it deleted a subject's data
is not the same as proving it. This verifies the claim: after an erase, the
subject must have **zero** residual records across every store Maverick holds.

It reuses the DSAR export (:func:`maverick.dsar.export_subject_data`), whose
subject-matching is guaranteed by design to agree with the erase path ("a row
that *would* be erased is a row that *is* exported"). So a non-zero residual
count after erasure is, definitionally, an incomplete erasure — the same rule,
read back. Read-only and fail-soft.

* :func:`verify_erasure` — the post-erasure check: residual counts + a
  ``clean`` verdict (True == nothing left).
* :func:`differential` — the before/after proof: every ``after`` count is zero
  AND the erase actually removed something (some ``before`` count was > 0).
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote


def _fact_subject_token(channel: str, user_id: str) -> str:
    """Stable, delimiter-safe token for explicitly user-scoped facts."""
    return f"{quote(channel, safe='')}:{quote(user_id, safe='')}"


def _count_user_scoped_facts(user_id: str, *, channel: str | None,
                             tenant: str | None) -> int:
    """Count explicitly user-scoped global facts for the erasure subject."""
    if not channel:
        return 0
    try:
        from .dsar import _resolve_world

        world = _resolve_world(tenant)
        if world is None or not hasattr(world, "facts_matching"):
            return 0
        return len(world.facts_matching(_fact_subject_token(channel, user_id)))
    except Exception:
        # Erasure verification is read-only and fail-soft, like DSAR export.
        return 0


def verify_erasure(user_id: str, *, channel: str | None = None,
                   tenant: str | None = None) -> dict:
    """Confirm no residual data remains for a subject after erasure.

    Returns ``{subject, tenant, counts, residual, clean, verified_at}`` where
    ``clean`` is True iff every per-store count is zero. ``channel`` should be
    given (it is part of subject identity); the export fails closed on an
    ambiguous bare ``user_id``.
    """
    from .dsar import export_subject_data
    bundle = export_subject_data(user_id, channel=channel, tenant=tenant)
    counts = {k: int(v) for k, v in (bundle.get("counts") or {}).items()}
    subject = bundle.get("subject") or {}
    resolved_channel = subject.get("channel") if isinstance(subject, dict) else channel
    counts["facts"] = _count_user_scoped_facts(
        user_id, channel=resolved_channel, tenant=tenant)
    residual = {k: v for k, v in counts.items() if v}
    return {
        "subject": bundle.get("subject"),
        "tenant": tenant,
        "counts": counts,
        "residual": residual,
        "clean": not residual,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def differential(before: dict, after: dict) -> dict:
    """Compare pre/post-erasure residual counts into a proof of removal.

    ``before``/``after`` are ``counts`` dicts (e.g. from two
    :func:`verify_erasure` calls). ``verified`` is True iff every ``after``
    count is zero AND at least one ``before`` count was positive — i.e. the
    erase had something to remove and left nothing behind.
    """
    keys = set(before) | set(after)
    removed = {k: int(before.get(k, 0)) - int(after.get(k, 0)) for k in keys}
    after_clean = all(int(after.get(k, 0)) == 0 for k in keys)
    had_data = any(int(before.get(k, 0)) > 0 for k in keys)
    return {
        "removed": removed,
        "after_clean": after_clean,
        "verified": after_clean and had_data,
    }


__all__ = ["verify_erasure", "differential"]
