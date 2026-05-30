"""Q2 2026 batch 6: calendar (CalDAV) tool, reflexion library."""
from __future__ import annotations

import time
from unittest.mock import MagicMock



# ---------- calendar tool ----------

def test_calendar_requires_op():
    from maverick.tools.calendar_tool import calendar_tool
    assert "op is required" in calendar_tool().fn({})


def test_calendar_unknown_op():
    from maverick.tools.calendar_tool import calendar_tool
    out = calendar_tool().fn({"op": "garbage"})
    assert "unknown op" in out


def test_calendar_create_requires_fields():
    from maverick.tools.calendar_tool import calendar_tool
    out = calendar_tool().fn({"op": "create_event"})
    assert "requires title + start + end" in out


def test_calendar_requires_credentials(monkeypatch):
    """Without env / config, the tool refuses with a clear message —
    either ImportError-flavored (no caldav lib) OR RuntimeError-
    flavored (lib installed, no creds)."""
    monkeypatch.delenv("CALDAV_URL", raising=False)
    monkeypatch.delenv("CALDAV_USER", raising=False)
    monkeypatch.delenv("CALDAV_PASSWORD", raising=False)
    monkeypatch.setenv("HOME", "/nonexistent-home-for-tests")
    # Force the caldav module to be present so we test the missing-creds
    # path rather than the missing-dep path.
    import sys
    import types
    fake_caldav = types.ModuleType("caldav")
    fake_caldav.DAVClient = MagicMock()
    monkeypatch.setitem(sys.modules, "caldav", fake_caldav)
    from maverick.tools.calendar_tool import calendar_tool
    out = calendar_tool().fn({"op": "list_events"})
    assert "CALDAV_URL" in out


def test_calendar_create_event_calls_caldav(monkeypatch):
    monkeypatch.setenv("CALDAV_URL", "https://cal.test")
    monkeypatch.setenv("CALDAV_USER", "me@test")
    monkeypatch.setenv("CALDAV_PASSWORD", "pw")

    # Build a fake caldav module hierarchy.
    import sys
    import types
    fake_caldav = types.ModuleType("caldav")

    fake_calendar = MagicMock()
    fake_saved = MagicMock()
    fake_saved.url = "https://cal.test/event/123"
    fake_calendar.save_event = MagicMock(return_value=fake_saved)

    fake_principal = MagicMock()
    fake_principal.calendars = MagicMock(return_value=[fake_calendar])

    fake_client = MagicMock()
    fake_client.principal = MagicMock(return_value=fake_principal)
    fake_caldav.DAVClient = MagicMock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "caldav", fake_caldav)

    from maverick.tools.calendar_tool import calendar_tool
    out = calendar_tool().fn({
        "op": "create_event",
        "title": "Meeting with Alice",
        "start": "2026-06-01T10:00:00",
        "end": "2026-06-01T11:00:00",
        "description": "monthly sync",
    })
    assert "created event" in out
    assert "https://cal.test/event/123" in out
    fake_calendar.save_event.assert_called_once()
    ical_arg = fake_calendar.save_event.call_args.args[0]
    assert "SUMMARY:Meeting with Alice" in ical_arg
    assert "DTSTART:20260601T100000Z" in ical_arg


def test_calendar_create_event_escapes_text_fields(monkeypatch):
    monkeypatch.setenv("CALDAV_URL", "https://cal.test")
    monkeypatch.setenv("CALDAV_USER", "me@test")
    monkeypatch.setenv("CALDAV_PASSWORD", "pw")

    import sys
    import types
    fake_caldav = types.ModuleType("caldav")

    fake_calendar = MagicMock()
    fake_saved = MagicMock()
    fake_saved.url = "https://cal.test/event/456"
    fake_calendar.save_event = MagicMock(return_value=fake_saved)

    fake_principal = MagicMock()
    fake_principal.calendars = MagicMock(return_value=[fake_calendar])
    fake_client = MagicMock()
    fake_client.principal = MagicMock(return_value=fake_principal)
    fake_caldav.DAVClient = MagicMock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "caldav", fake_caldav)

    from maverick.tools.calendar_tool import calendar_tool
    calendar_tool().fn({
        "op": "create_event",
        "title": "Team sync\nRRULE:FREQ=DAILY",
        "start": "2026-06-01T10:00:00",
        "end": "2026-06-01T11:00:00",
        "description": "normal\nBEGIN:VALARM",
    })
    ical_arg = fake_calendar.save_event.call_args.args[0]
    assert "SUMMARY:Team sync\\nRRULE:FREQ=DAILY" in ical_arg
    assert "DESCRIPTION:normal\\nBEGIN:VALARM" in ical_arg
    assert "\nRRULE:FREQ=DAILY\n" not in ical_arg
    assert "\nBEGIN:VALARM\n" not in ical_arg


def test_calendar_find_slot_picks_free_window(monkeypatch):
    """find_slot returns the first gap that fits the requested duration."""
    monkeypatch.setenv("CALDAV_URL", "https://cal.test")
    monkeypatch.setenv("CALDAV_USER", "me@test")
    monkeypatch.setenv("CALDAV_PASSWORD", "pw")

    import sys
    import types
    fake_caldav = types.ModuleType("caldav")

    fake_calendar = MagicMock()
    # No events at all -> the first earliest-hour minute on the next
    # search-day is the free slot.
    fake_calendar.search = MagicMock(return_value=[])

    fake_principal = MagicMock()
    fake_principal.calendars = MagicMock(return_value=[fake_calendar])

    fake_client = MagicMock()
    fake_client.principal = MagicMock(return_value=fake_principal)
    fake_caldav.DAVClient = MagicMock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "caldav", fake_caldav)

    from maverick.tools.calendar_tool import calendar_tool
    out = calendar_tool().fn({
        "op": "find_slot",
        "duration_minutes": 45,
        "search_days": 1,
        "earliest_hour": 9, "latest_hour": 18,
    })
    assert "free slot:" in out
    assert "45 min" in out


def test_calendar_in_registry():
    from maverick.tools import base_registry

    class _FakeSandbox:
        workdir = "."

    class _FakeWorld:
        pass

    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())
    names = {t.name for t in reg.all()}
    assert "calendar" in names


# ---------- reflexion ----------

def test_reflexion_record_and_recall(tmp_path):
    from maverick.reflexion import recall, record
    p = tmp_path / "reflexions.ndjson"
    assert record(
        "Refactor the auth module to use sessions",
        "auth",
        "401 Unauthorized when calling /api/login",
        "I should have read the existing session middleware before refactoring.",
        tools_used=["read_file", "shell"],
        path=p,
    )
    assert p.exists()
    hits = recall("refactor auth module sessions", k=3, path=p)
    assert len(hits) == 1
    score, r = hits[0]
    assert score > 0.3
    assert r.failure_class == "auth"
    assert "session" in r.reflection.lower()


def test_reflexion_recall_ranks_by_similarity(tmp_path):
    from maverick.reflexion import recall, record
    p = tmp_path / "reflexions.ndjson"
    record(
        "Refactor the cart checkout flow",
        "logic_bug",
        "cart total off by one",
        "I miscounted line items.",
        path=p,
    )
    record(
        "Refactor the auth module to use sessions",
        "auth",
        "401",
        "lesson about session middleware",
        path=p,
    )
    record(
        "Plan a 3-day trip to Lisbon",
        "unknown",
        "no failure, just unrelated content",
        "n/a",
        path=p,
    )
    hits = recall("refactor authentication sessions", k=2, path=p)
    assert len(hits) >= 1
    # The auth refactor entry should rank above the cart refactor entry.
    top = hits[0][1]
    assert "auth" in top.goal_text.lower()


def test_reflexion_recall_empty_file(tmp_path):
    from maverick.reflexion import recall
    p = tmp_path / "nonexistent.ndjson"
    assert recall("anything", path=p) == []


def test_reflexion_recall_no_query(tmp_path):
    from maverick.reflexion import recall, record
    p = tmp_path / "x.ndjson"
    record("g", "k", "m", "r", path=p)
    assert recall("", path=p) == []


def test_reflexion_list_recent_newest_first(tmp_path):
    from maverick.reflexion import list_recent, record
    p = tmp_path / "x.ndjson"
    record("first", "k", "m", "r", path=p)
    time.sleep(0.01)
    record("second", "k", "m", "r", path=p)
    time.sleep(0.01)
    record("third", "k", "m", "r", path=p)
    entries = list_recent(limit=10, path=p)
    assert [e.goal_text for e in entries] == ["third", "second", "first"]


def test_reflexion_clear(tmp_path):
    from maverick.reflexion import clear, recall, record
    p = tmp_path / "x.ndjson"
    record("g", "k", "m", "r", path=p)
    assert p.exists()
    assert clear(path=p) is True
    assert not p.exists()
    assert recall("g", path=p) == []


def test_reflexion_file_perms_600(tmp_path):
    """File should be created with mode 0600."""
    import os
    import stat
    from maverick.reflexion import record
    p = tmp_path / "perm.ndjson"
    record("g", "k", "m", "r", path=p)
    assert p.exists()
    mode = stat.S_IMODE(p.stat().st_mode)
    # 0o600 OR 0o644 depending on umask + test env; the helper does
    # chmod 600 but we don't fail if the FS quietly refuses. POSIX-only:
    # NTFS reports 0o666 and os.geteuid() doesn't exist on Windows.
    if os.name != "nt":
        assert (mode & 0o077) == 0 or os.geteuid() == 0


def test_reflexion_format_context_renders_sections():
    from maverick.reflexion import Reflexion, format_context
    r = Reflexion(
        ts=time.time(),
        goal_text="Refactor auth",
        failure_class="auth",
        failure_msg="401",
        reflection="Read middleware first next time.",
    )
    out = format_context([(0.85, r)])
    assert "Prior failures on similar goals" in out
    assert "Refactor auth" in out
    assert "Read middleware first" in out


def test_reflexion_format_context_empty_returns_empty():
    from maverick.reflexion import format_context
    assert format_context([]) == ""


def test_reflexion_record_failsafe_on_bad_path(tmp_path):
    """Writing to a path under a file (cannot create) is a soft failure."""
    from maverick.reflexion import record
    blocking = tmp_path / "blocker"
    blocking.write_text("x")
    bad = blocking / "subdir" / "f.ndjson"
    # Recording must NOT raise; returns False.
    ok = record("g", "k", "m", "r", path=bad)
    assert ok is False
