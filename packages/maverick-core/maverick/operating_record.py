"""The Operating Record: the firm's decisions as a system of record.

ERP capitalized money, CRM customers, HRIS people. The last uncapitalized
asset is judgment — how the company decides. The substrate already records
its raw material (goals with departments, episodes with outcomes and spend,
human approvals with deciders, the signed audit chain, the distilled
learned state); this module threads those existing stores into one
queryable spine of :class:`DecisionRecord` rows and exports the whole
operating mind as a signed, portable **capsule**.

v1 scope (deliberate): assemble + query + signed export. Merge/split (M&A
integration as a merge operation) builds on the capsule format later.
Read-only over the world model — assembling the Record never mutates what
it records. Export is Ed25519-signed with the instance's audit keypair, so
a capsule's integrity and origin are verifiable offline (the same
fail-closed pattern as the insight exchange).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


@dataclass
class DecisionRecord:
    """One unit of the firm's judgment, with its context and outcome."""
    ts: float
    kind: str                       # "goal" | "approval"
    actor: str                      # agent department / human principal
    department: str = ""
    subject: str = ""               # what was decided (bounded)
    outcome: str = ""               # done/blocked / approved/denied
    cost_dollars: float = 0.0
    goal_id: int | None = None
    decided_by: str | None = None   # human principal for approvals
    provenance: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RecordStats:
    n_records: int = 0
    n_goals: int = 0
    n_approvals: int = 0
    n_human_decisions: int = 0
    departments: dict[str, int] = field(default_factory=dict)


def _goal_records(
    world: Any, *, limit: int, owner: str | None = None,
) -> list[DecisionRecord]:
    out: list[DecisionRecord] = []
    try:
        kwargs: dict[str, Any] = {"limit": limit, "order": "desc"}
        if owner is not None:
            kwargs["owner"] = owner
        goals = world.list_goals(**kwargs)
    except Exception as e:  # pragma: no cover -- assembly never raises
        log.debug("operating_record: goal read failed: %s", e)
        return out
    spend: dict[int, float] = {}
    try:
        kwargs = {"limit": limit * 4}
        if owner is not None:
            kwargs["owner"] = owner
        for ep in world.list_episodes(**kwargs):
            gid = getattr(ep, "goal_id", None)
            if gid is not None:
                spend[gid] = spend.get(gid, 0.0) + float(
                    getattr(ep, "cost_dollars", 0) or 0)
    except Exception:  # pragma: no cover
        pass
    for g in goals:
        dept = getattr(g, "domain", "") or ""
        out.append(DecisionRecord(
            ts=float(getattr(g, "updated_at", 0) or 0),
            kind="goal",
            actor=dept or "orchestrator",
            department=dept,
            subject=str(getattr(g, "title", "") or "")[:200],
            outcome=str(getattr(g, "status", "") or ""),
            cost_dollars=round(spend.get(getattr(g, "id", -1), 0.0), 4),
            goal_id=getattr(g, "id", None),
        ))
    return out


def _approval_records(
    world: Any, *, limit: int, owner: str | None = None,
) -> list[DecisionRecord]:
    out: list[DecisionRecord] = []
    try:
        approvals = world.list_approvals(limit=limit)
    except Exception as e:  # pragma: no cover -- older DBs lack the API
        log.debug("operating_record: approval read failed: %s", e)
        return out
    for a in approvals:
        if owner is not None and owner not in {
            getattr(a, "requested_by", None),
            getattr(a, "claimed_by", None),
            getattr(a, "decided_by", None),
        }:
            continue
        out.append(DecisionRecord(
            ts=float(getattr(a, "decided_at", None)
                     or getattr(a, "requested_at", 0) or 0),
            kind="approval",
            actor=str(getattr(a, "decided_by", None) or "pending"),
            subject=str(getattr(a, "action", "") or "")[:200],
            outcome=str(getattr(a, "status", "") or ""),
            decided_by=getattr(a, "decided_by", None),
            provenance=getattr(a, "provenance", None),
        ))
    return out


def assemble(
    world: Any, *, limit: int = 500, owner: str | None = None,
) -> list[DecisionRecord]:
    """The Operating Record: goal decisions + human approvals, newest first.

    ``owner`` scopes the record to one caller principal. ``None`` preserves the
    historical admin / auth-off view across all principals.
    """
    records = _goal_records(world, limit=limit, owner=owner) + \
        _approval_records(world, limit=limit, owner=owner)
    records.sort(key=lambda r: r.ts, reverse=True)
    return records[:limit]


def query(
    records: list[DecisionRecord], *, text: str = "", department: str = "",
    actor: str = "", kind: str = "",
) -> list[DecisionRecord]:
    """Filter the Record ("every decision that touched X"). Pure."""
    needle = text.strip().lower()
    out = []
    for r in records:
        if department and r.department != department:
            continue
        if actor and actor not in (r.actor or "") and actor != (r.decided_by or ""):
            continue
        if kind and r.kind != kind:
            continue
        if needle and needle not in (r.subject or "").lower():
            continue
        out.append(r)
    return out


def stats(records: list[DecisionRecord]) -> RecordStats:
    s = RecordStats(n_records=len(records))
    for r in records:
        if r.kind == "goal":
            s.n_goals += 1
        elif r.kind == "approval":
            s.n_approvals += 1
            if r.decided_by:
                s.n_human_decisions += 1
        if r.department:
            s.departments[r.department] = s.departments.get(r.department, 0) + 1
    return s


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")


def export_capsule(
    world: Any, out_path: Path | str, *, limit: int = 500,
    now: float | None = None,
) -> Path:
    """Export the operating mind as one signed, portable artifact.

    Contents: the decision spine + the learned state (insights, learned
    skills, rehearsal queue — the same stores a dream snapshot covers,
    inlined) + a signed manifest. Verifiable offline via
    :func:`verify_capsule`. Raises without ``cryptography`` — an unsigned
    operating mind is not an asset, it's a leak.
    """
    from .audit.signing import _have_crypto, _load_or_create_keypair
    if not _have_crypto():
        raise RuntimeError(
            "capsule export requires 'cryptography' "
            "(install 'maverick-agent[audit-signing]'): capsules are always signed."
        )
    from cryptography.hazmat.primitives.asymmetric import ed25519

    records = [r.to_dict() for r in assemble(world, limit=limit)]
    learned: dict[str, Any] = {}
    try:
        from . import dreaming
        learned["insights"] = [i.to_dict() for i in dreaming.load_insights()]
        learned["rehearsals"] = dreaming.load_rehearsals()
        from .skill.distillation_local import _STORE
        skills_dir = dreaming._tenant_path("learned-skills", _STORE)
        learned["skills"] = {
            p.stem: p.read_text(encoding="utf-8")
            for p in (sorted(Path(skills_dir).glob("*.md"))
                      if Path(skills_dir).is_dir() else [])
        }
    except Exception as e:  # pragma: no cover -- partial capsule beats none
        log.debug("operating_record: learned-state inline skipped: %s", e)

    ts = now if now is not None else time.time()
    body = {
        "schema_version": SCHEMA_VERSION, "ts": ts,
        "records": records, "learned": learned,
    }
    priv, pub, key_id = _load_or_create_keypair()
    sig = ed25519.Ed25519PrivateKey.from_private_bytes(priv).sign(
        _canonical(body))
    capsule = {**body, "pubkey": pub.hex(), "key_id": key_id,
               "sig": sig.hex()}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: a crash mid-write must not leave a truncated capsule that
    # verify_capsule would then flag as unreadable / invalid-signature. Write a
    # temp sibling, then atomically replace -- the path is always either the old
    # capsule or the complete new one.
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(capsule, indent=2, default=str), encoding="utf-8")
    tmp.replace(out)
    try:
        from .audit import EventKind, record
        record(EventKind.LEARNING_UPDATE, agent="operating_record",
               capsule="export", n_records=len(records), key_id=key_id)
    except Exception:  # pragma: no cover
        pass
    return out


def verify_capsule(path: Path | str) -> tuple[bool, str]:
    """Offline integrity + origin check. Returns ``(ok, reason)``."""
    try:
        capsule = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return False, f"unreadable capsule: {e}"
    sig = str(capsule.get("sig", "") or "")
    pub = str(capsule.get("pubkey", "") or "")
    if not sig or not pub:
        return False, "capsule is unsigned"
    body = {k: capsule[k] for k in
            ("schema_version", "ts", "records", "learned") if k in capsule}
    from .audit.signing import _have_crypto, verify_ed25519
    if not _have_crypto():
        return False, "cryptography not installed: cannot verify"
    if not verify_ed25519(pub, sig, _canonical(body)):
        return False, "signature verification FAILED"
    return True, f"ok: {len(body.get('records', []))} record(s), key {capsule.get('key_id', pub[:8])}"


__all__ = [
    "SCHEMA_VERSION", "DecisionRecord", "RecordStats", "assemble", "query",
    "stats", "export_capsule", "verify_capsule",
]
