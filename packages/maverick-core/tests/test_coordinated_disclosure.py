"""coordinated_disclosure: CVD ledger validation."""
from __future__ import annotations

from maverick.tools.coordinated_disclosure import coordinated_disclosure


def _run(**kw):
    return coordinated_disclosure().fn(kw)


def test_add_ok():
    out = _run(op="add", report={"id": "CVE-1", "severity": "high", "status": "received"})
    assert out.startswith("OK") and "CVE-1" in out and "status=received" in out


def test_add_invalid_status():
    out = _run(op="add", report={"id": "X", "severity": "low", "status": "bogus"})
    assert out.startswith("ERROR") and "invalid status" in out


def test_add_missing_id():
    out = _run(op="add", report={"severity": "low", "status": "received"})
    assert out.startswith("ERROR") and "id is required" in out


def test_validate_counts_clean():
    out = _run(op="validate", reports=[
        {"id": "a", "severity": "low", "status": "received"},
        {"id": "b", "severity": "high", "status": "fixed"},
        {"id": "c", "severity": "high", "status": "fixed"},
    ])
    assert out.startswith("CLEAN")
    assert "received=1" in out and "fixed=2" in out


def test_validate_flags_bad_transition():
    # published directly from received skips triaged+fixed -> invalid.
    out = _run(op="validate", reports=[
        {"id": "a", "severity": "critical", "status": "published", "prev_status": "received"},
    ])
    assert out.startswith("RISK")
    assert "invalid transition received -> published" in out


def test_validate_good_transition():
    out = _run(op="validate", reports=[
        {"id": "a", "severity": "high", "status": "fixed", "prev_status": "triaged"},
    ])
    assert out.startswith("CLEAN") and "fixed=1" in out


def test_unknown_op():
    assert _run(op="nope").startswith("ERROR")
    assert _run(op="validate", reports="x").startswith("ERROR")
