"""Audit-log lifecycle hardening (#462).

Covers four fixes to the audit erase/write path:

  1. GDPR erase matches on STRUCTURED channel+user_id fields only -- it must
     match ``slack``+``42`` but never over-match ``slack:4200`` via a substring
     of a serialized value (and never under-match a ``slack/42`` encoding).
  2. A same-process erase-then-record verifies clean: erase resets the live
     signer's stale in-memory chain head so the next record() chains onto the
     re-anchored tail, not a hash no longer in the file.
  3. The unsigned write path fsyncs (durability parity with the signed path).
  4. Concurrent appends serialize under an advisory flock.
"""

from __future__ import annotations

import json

import pytest


def _have_crypto() -> bool:
    try:
        import cryptography  # noqa: F401

        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Task 1: structured erase match (no signing required)
# ---------------------------------------------------------------------------


def _write_plain(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def test_erase_matches_structured_user_not_substring(tmp_path):
    from maverick.audit.erase import delete_user

    ad = tmp_path / "audit"
    path = ad / "2026-01-01.ndjson"
    _write_plain(
        path,
        [
            {"v": 1, "ts": 1.0, "kind": "goal_start", "channel": "slack", "user_id": "42"},
            {"v": 1, "ts": 2.0, "kind": "goal_start", "channel": "slack", "user_id": "4200"},
        ],
    )

    deleted, _ = delete_user("slack", "42", audit_dir=ad)
    assert deleted == 1, "exact structured match only -- slack:4200 must survive"

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["user_id"] == "4200"


def test_erase_matches_structured_even_with_slashed_serialization(tmp_path):
    """A row whose serialized form would read ``slack/42`` (never ``slack:42``)
    must STILL match, because matching is on the structured fields."""
    from maverick.audit.erase import delete_user

    ad = tmp_path / "audit"
    path = ad / "2026-01-02.ndjson"
    _write_plain(
        path,
        [
            {"v": 1, "ts": 1.0, "kind": "tool_call", "channel": "slack", "user_id": "42",
             "input_summary": "posted to slack/42"},
        ],
    )

    deleted, _ = delete_user("slack", "42", audit_dir=ad)
    assert deleted == 1
    assert path.read_text(encoding="utf-8").strip() == ""


def test_erase_does_not_match_substring_only_rows(tmp_path):
    """A row that merely *mentions* ``slack:42`` in a free-text field but has no
    structured channel/user_id must NOT be erased (no substring fallback)."""
    from maverick.audit.erase import delete_user

    ad = tmp_path / "audit"
    path = ad / "2026-01-03.ndjson"
    _write_plain(
        path,
        [
            {"v": 1, "ts": 1.0, "kind": "tool_call", "input_summary": "ref slack:42 in a log line"},
        ],
    )

    deleted, _ = delete_user("slack", "42", audit_dir=ad)
    assert deleted == 0
    assert path.read_text(encoding="utf-8").strip() != ""


def test_erase_scrubs_capability_denial_with_structured_subject(tmp_path):
    """Capability-denial audit events may carry an identifying principal.

    They must also carry structured channel/user_id fields so user erasure can
    tombstone the row and remove that principal instead of leaving it in audit
    tail/search output.
    """
    from maverick.audit.erase import scrub_user

    ad = tmp_path / "audit"
    path = ad / "2026-01-04.ndjson"
    _write_plain(
        path,
        [
            {
                "v": 1,
                "ts": 1.0,
                "kind": "capability_denied",
                "tool": "shell",
                "principal": "user:sms:+15551234567",
                "channel": "sms",
                "user_id": "sms:+15551234567",
            },
        ],
    )

    matched, scanned = scrub_user("sms", "sms:+15551234567", audit_dir=ad)
    assert matched == 1
    assert scanned == 1
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["kind"] == "capability_denied"
    assert row["user_id"] == "[REDACTED]"
    assert "principal" not in row
    assert "+15551234567" not in json.dumps(row)


# ---------------------------------------------------------------------------
# Task 3: unsigned write path fsync
# ---------------------------------------------------------------------------


def test_unsigned_record_fsyncs(tmp_path, monkeypatch):
    from maverick.audit import writer as W
    from maverick.audit.events import AuditEvent
    from maverick.audit.writer import AuditLog

    monkeypatch.delenv("MAVERICK_AUDIT_SIGN", raising=False)
    fsynced: list[int] = []
    monkeypatch.setattr(W.os, "fsync", lambda fd: fsynced.append(fd))

    log = AuditLog(audit_dir=tmp_path, sign=False)
    assert log.record(AuditEvent(ts=1.0, kind="tool_call", agent="a", payload={}))
    assert fsynced, "unsigned audit write must fsync the row"


# ---------------------------------------------------------------------------
# Task 4: concurrent appends serialize under flock (POSIX)
# ---------------------------------------------------------------------------


def test_unsigned_record_acquires_flock(tmp_path, monkeypatch):
    """The unsigned append takes an exclusive advisory flock and releases it."""
    fcntl = pytest.importorskip("fcntl")
    from maverick.audit.events import AuditEvent
    from maverick.audit.writer import AuditLog

    calls: list[int] = []
    real_flock = fcntl.flock
    monkeypatch.setattr(
        fcntl, "flock", lambda fd, op: (calls.append(op), real_flock(fd, op))[1]
    )

    log = AuditLog(audit_dir=tmp_path, sign=False)
    assert log.record(AuditEvent(ts=1.0, kind="tool_call", agent="a", payload={}))
    assert fcntl.LOCK_EX in calls, "append must acquire an exclusive flock"
    assert fcntl.LOCK_UN in calls, "the flock must be released after the append"


def test_concurrent_unsigned_appends_do_not_interleave(tmp_path):
    """Two processes appending big rows to the same day-file must not interleave
    torn records: every line stays valid JSON and the count is exact."""
    pytest.importorskip("fcntl")
    import multiprocessing as mp

    ad = tmp_path / "audit"
    ad.mkdir(parents=True)

    def _worker(audit_dir, tag, n):
        from maverick.audit.events import AuditEvent
        from maverick.audit.writer import AuditLog

        log = AuditLog(audit_dir=audit_dir, sign=False)
        big = tag * 8000  # well above PIPE_BUF so single-write atomicity fails
        for i in range(n):
            log.record(AuditEvent(ts=float(i), kind="tool_call", agent=tag,
                                  payload={"blob": big}))

    n = 40
    procs = [mp.Process(target=_worker, args=(ad, tag, n)) for tag in ("a", "b")]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    files = list(ad.glob("*.ndjson"))
    assert len(files) == 1
    lines = [ln for ln in files[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2 * n, f"expected {2 * n} rows, got {len(lines)}"
    for ln in lines:
        json.loads(ln)  # raises if any record was torn / interleaved


# ---------------------------------------------------------------------------
# Task 2: same-process erase-then-record verifies clean
# ---------------------------------------------------------------------------


@pytest.fixture
def _isolate_keys(monkeypatch, tmp_path):
    from maverick.audit import signing

    monkeypatch.setattr(signing, "KEY_DIR", tmp_path / "keys")


@pytest.mark.skipif(not _have_crypto(), reason="cryptography not installed")
def test_same_process_erase_then_record_verifies_clean(_isolate_keys, tmp_path):
    """erase resets the live signer so a later record() in the SAME process
    chains onto the re-anchored tail -- no explicit reanchor_after_erase()."""
    from maverick.audit.erase import scrub_user
    from maverick.audit.events import AuditEvent, EventKind
    from maverick.audit.signing import verify_chain
    from maverick.audit.writer import AuditLog

    ad = tmp_path / "audit"
    log = AuditLog(audit_dir=ad, sign=True)
    ts = 1000.0
    for ch, uid in [("slack", "alice"), ("slack", "bob"), ("slack", "alice")]:
        assert log.record(
            AuditEvent(ts=ts, kind=EventKind.GOAL_START,
                       payload={"channel": ch, "user_id": uid, "title": f"{uid} goal"})
        )
        ts += 1.0
    path = sorted(ad.glob("*.ndjson"))[0]
    assert verify_chain(path) == []

    matched, _ = scrub_user("slack", "alice", audit_dir=ad)
    assert matched == 2
    assert verify_chain(path) == []

    # No explicit reanchor_after_erase(): the erase already reset the live
    # signer, so this record() must extend the rewritten chain cleanly.
    assert log.record(
        AuditEvent(ts=2000.0, kind=EventKind.GOAL_END,
                   payload={"status": "succeeded", "result": None})
    )
    assert verify_chain(path) == [], "erase-then-record must not chain_mismatch"
