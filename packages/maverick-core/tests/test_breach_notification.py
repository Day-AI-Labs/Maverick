"""breach_notification: GDPR Art. 33/34 72h notification timer."""
from __future__ import annotations

from maverick.tools.breach_notification import breach_notification


def _s(**kw):
    kw.setdefault("op", "status")
    return breach_notification().fn(kw)


def test_due_within_window():
    out = _s(discovered="2026-06-10T00:00:00", now="2026-06-11T00:00:00")
    assert out.startswith("DUE")
    # deadline 72h after discovery = 2026-06-13T00:00:00, 48h remaining
    assert "2026-06-13T00:00:00" in out and "in 48.0h" in out


def test_overdue():
    out = _s(discovered="2026-06-10T00:00:00", now="2026-06-14T00:00:00")
    assert out.startswith("OVERDUE")
    assert "overdue 24.0h" in out


def test_notified_on_time():
    out = _s(discovered="2026-06-10T00:00:00", notified="2026-06-11T12:00:00")
    assert out.startswith("ON_TIME")
    assert "36.0h after discovery" in out


def test_notified_late():
    out = _s(discovered="2026-06-10T00:00:00", notified="2026-06-14T00:00:00")
    assert out.startswith("LATE")
    assert "late 24.0h" in out


def test_high_risk_art34_reminder():
    out = _s(discovered="2026-06-10T00:00:00", now="2026-06-10T01:00:00", high_risk=True)
    assert out.startswith("DUE")
    assert "Art. 34" in out and "HIGH RISK" in out


def test_z_suffix_and_date_only():
    # 'Z' suffix and a date-only discovery both parse
    out = _s(discovered="2026-06-10", now="2026-06-11T00:00:00Z")
    assert out.startswith("DUE")


def test_custom_deadline_hours():
    out = _s(discovered="2026-06-10T00:00:00", now="2026-06-10T05:00:00", deadline_hours=4)
    assert out.startswith("OVERDUE")


def test_errors():
    t = breach_notification()
    assert t.fn({"op": "status"}).startswith("ERROR")
    assert t.fn({"op": "status", "discovered": "nope"}).startswith("ERROR")
    assert t.fn({"op": "status", "discovered": "2026-06-10", "deadline_hours": 0}).startswith("ERROR")
    assert t.fn({"op": "status", "discovered": "2026-06-10", "notified": "2026-06-09"}).startswith("ERROR")
    assert t.fn({"op": "nope", "discovered": "2026-06-10"}).startswith("ERROR")


def test_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        workdir = "."

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    assert "breach_notification" in names
