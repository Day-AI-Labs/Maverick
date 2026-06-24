"""Tests for governed AI-system retirement: the ordered archive/erase/record
flow, the safe-default disposition coercion, fail-safe degradation when a
side-effect raises, and the injected clock."""
from __future__ import annotations

from maverick import retirement as rt


def _recorder():
    """A record_event callable that captures the RetirementRecord and returns ok."""
    seen = []

    def record_event(rec):
        seen.append(rec)
        return True

    return seen, record_event


class TestDisposition:
    def test_archive_path_snapshots_and_records(self):
        archived = []
        seen, record_event = _recorder()
        rec = rt.retire_system(
            "coder-role", reason="superseded", decided_by="alice",
            data_disposition="archive",
            archive=lambda sid: archived.append(sid),
            dispose=lambda sid: archived.append("DISPOSE"),  # must NOT be called
            record_event=record_event)
        assert archived == ["coder-role"]  # archive ran, dispose did not
        assert rec.archived and not rec.erased
        assert rec.recorded and seen[0] is rec

    def test_erase_path_disposes_and_records(self):
        disposed = []
        seen, record_event = _recorder()
        rec = rt.retire_system(
            "legacy-model", reason="eol", decided_by="bob",
            data_disposition="erase",
            archive=lambda sid: disposed.append("ARCHIVE"),  # must NOT be called
            dispose=lambda sid: disposed.append(sid),
            record_event=record_event)
        assert disposed == ["legacy-model"]
        assert rec.erased and not rec.archived
        assert rec.recorded

    def test_retain_path_neither_archives_nor_disposes(self):
        calls = []
        _seen, record_event = _recorder()
        rec = rt.retire_system(
            "kept", reason="paused", decided_by="carol", data_disposition="retain",
            archive=lambda sid: calls.append("a"), dispose=lambda sid: calls.append("d"),
            record_event=record_event)
        assert calls == []
        assert not rec.archived and not rec.erased
        assert rec.data_disposition == "retain"

    def test_unknown_disposition_coerced_to_archive_with_note(self):
        rec = rt.retire_system("x", reason="r", decided_by="d",
                               data_disposition="nuke-it")
        assert rec.data_disposition == "archive"
        assert "coerced to 'archive'" in rec.notes


class TestFailSafe:
    def test_failed_archive_degrades_but_still_records(self):
        seen, record_event = _recorder()

        def boom(_sid):
            raise RuntimeError("disk full")

        rec = rt.retire_system("s", reason="r", decided_by="d",
                               data_disposition="archive",
                               archive=boom, record_event=record_event)
        assert not rec.archived
        assert "archive failed" in rec.notes
        assert rec.recorded  # the act is still audited

    def test_failed_record_event_does_not_raise(self):
        def boom(_rec):
            raise RuntimeError("audit sink down")

        rec = rt.retire_system("s", reason="r", decided_by="d",
                               data_disposition="retain", record_event=boom)
        assert rec.recorded is False  # degraded, not raised

    def test_record_event_returning_false_sets_recorded_false(self):
        rec = rt.retire_system("s", reason="r", decided_by="d",
                               data_disposition="retain",
                               record_event=lambda _rec: False)
        assert rec.recorded is False


class TestClock:
    def test_injected_clock_sets_ts(self):
        rec = rt.retire_system("s", reason="r", decided_by="d", now=lambda: 123.0)
        assert rec.ts == 123.0

    def test_broken_clock_degrades_to_none(self):
        def bad():
            raise OSError("clock")

        rec = rt.retire_system("s", reason="r", decided_by="d", now=bad)
        assert rec.ts is None


def test_dispositions_constant():
    assert rt.DISPOSITIONS == ("retain", "archive", "erase")
