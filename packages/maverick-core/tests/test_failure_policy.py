"""Tests for the failure-policy classification lint (maverick.failure_policy).

The lint requires every broad exception handler in the scoped audit-integrity
subsystem to declare its failure mode via a `# failure-policy: <class>` marker.
"""
from __future__ import annotations

from pathlib import Path

from maverick import failure_policy as fp


def test_real_audit_tree_is_fully_classified():
    """The shipped audit subsystem has every broad except marked (the gate)."""
    assert fp.scan() == {}
    assert fp.main([]) == 0


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "mod.py"
    p.write_text(body, encoding="utf-8")
    return p


def test_unmarked_broad_except_is_flagged(tmp_path):
    p = _write(tmp_path, "try:\n    x = 1\nexcept Exception:\n    pass\n")
    probs = fp.scan_file(p)
    assert len(probs) == 1
    assert "without a # failure-policy" in probs[0][1]


def test_marker_on_except_line_passes(tmp_path):
    p = _write(
        tmp_path,
        "try:\n    x = 1\nexcept Exception:  # failure-policy: best_effort\n    pass\n",
    )
    assert fp.scan_file(p) == []


def test_marker_on_line_above_passes(tmp_path):
    p = _write(
        tmp_path,
        "try:\n    x = 1\n    # failure-policy: fail_closed\nexcept Exception:\n    raise\n",
    )
    assert fp.scan_file(p) == []


def test_invalid_class_is_flagged(tmp_path):
    p = _write(
        tmp_path,
        "try:\n    x = 1\n    # failure-policy: oops\nexcept Exception:\n    pass\n",
    )
    probs = fp.scan_file(p)
    assert len(probs) == 1
    assert "invalid failure-policy class" in probs[0][1]


def test_bare_baseexception_and_tuple_are_broad(tmp_path):
    src = (
        "try:\n    x = 1\nexcept:\n    pass\n"
        "try:\n    x = 1\nexcept BaseException:\n    pass\n"
        "try:\n    x = 1\nexcept (ValueError, Exception):\n    pass\n"
    )
    p = _write(tmp_path, src)
    # All three are broad + unmarked -> three problems.
    assert len(fp.scan_file(p)) == 3


def test_narrow_except_needs_no_marker(tmp_path):
    p = _write(tmp_path, "try:\n    x = 1\nexcept ValueError:\n    pass\n")
    assert fp.scan_file(p) == []


def test_all_classes_accepted(tmp_path):
    for cls in fp.CLASSES:
        p = _write(
            tmp_path,
            f"try:\n    x = 1\nexcept Exception:  # failure-policy: {cls}\n    pass\n",
        )
        assert fp.scan_file(p) == [], cls
