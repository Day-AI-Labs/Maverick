"""WORM export of closed audit day-files (audit/worm.py).

Orchestration is exercised against a fake/local sink + a tmp audit dir (no S3),
the way the rest of the audit suite avoids live infra.
"""
from __future__ import annotations

import datetime as dt
import stat
from pathlib import Path

import pytest
from maverick.audit import worm


class FakeSink:
    def __init__(self):
        self.puts = []

    def put(self, name, data, *, retain_until):
        self.puts.append((name, data, retain_until))
        return {"target": "fake", "name": name}


def _audit_dir(tmp_path, files: dict[str, str]) -> Path:
    ad = tmp_path / "audit"
    ad.mkdir()
    for name, content in files.items():
        (ad / name).write_text(content, encoding="utf-8")
    return ad


# --- push -------------------------------------------------------------------

def test_push_ships_closed_skips_today_and_anchors(tmp_path):
    ad = _audit_dir(tmp_path, {
        "2020-01-01.ndjson": "a\n",
        "2020-01-02.ndjson": "b\n",
        "2099-01-01.ndjson": "future\n",   # >= today -> not closed
        "anchors.ndjson": "anchor\n",      # not a date-named day-file
    })
    sink = FakeSink()
    rep = worm.push_closed_dayfiles(audit_dir=ad, today="2025-01-01", sink=sink)
    assert rep == {"2020-01-01.ndjson": "pushed", "2020-01-02.ndjson": "pushed"}
    assert {n for n, _, _ in sink.puts} == {"2020-01-01.ndjson", "2020-01-02.ndjson"}
    # retain-until is in the future (the lock duration).
    assert all(ru > worm._utcnow() for _, _, ru in sink.puts)


def test_push_is_idempotent(tmp_path):
    ad = _audit_dir(tmp_path, {"2020-01-01.ndjson": "a\n"})
    sink = FakeSink()
    worm.push_closed_dayfiles(audit_dir=ad, today="2025-01-01", sink=sink)
    rep = worm.push_closed_dayfiles(audit_dir=ad, today="2025-01-01", sink=sink)
    assert rep == {"2020-01-01.ndjson": "already pushed"}
    assert len(sink.puts) == 1   # no second shipment


def test_changed_file_is_repushed(tmp_path):
    ad = _audit_dir(tmp_path, {"2020-01-01.ndjson": "a\n"})
    f = ad / "2020-01-01.ndjson"
    sink = FakeSink()
    worm.push_closed_dayfiles(audit_dir=ad, today="2025-01-01", sink=sink)
    f.write_text("a\nSEALED\n", encoding="utf-8")   # e.g. `audit seal` rewrote it
    rep = worm.push_closed_dayfiles(audit_dir=ad, today="2025-01-01", sink=sink)
    assert rep == {"2020-01-01.ndjson": "re-pushed (changed)"}
    assert len(sink.puts) == 2


def test_dry_run_writes_nothing(tmp_path):
    ad = _audit_dir(tmp_path, {"2020-01-01.ndjson": "a\n"})
    rep = worm.push_closed_dayfiles(audit_dir=ad, today="2025-01-01", dry_run=True)
    assert rep == {"2020-01-01.ndjson": "would push"}
    assert not (ad / "worm").exists()   # no manifest, no sink built


def test_push_unconfigured_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(worm, "_worm_cfg", dict)
    ad = _audit_dir(tmp_path, {"2020-01-01.ndjson": "a\n"})
    with pytest.raises(worm.WormUnavailable):
        worm.push_closed_dayfiles(audit_dir=ad, today="2025-01-01")


# --- verify -----------------------------------------------------------------

def test_verify_reports_ok_changed_and_unpushed(tmp_path):
    ad = _audit_dir(tmp_path, {
        "2020-01-01.ndjson": "a\n",
        "2020-01-02.ndjson": "b\n",
    })
    sink = FakeSink()
    worm.push_closed_dayfiles(audit_dir=ad, today="2025-01-01", sink=sink)
    (ad / "2020-01-02.ndjson").write_text("b changed\n", encoding="utf-8")
    (ad / "2020-01-03.ndjson").write_text("c\n", encoding="utf-8")   # never pushed
    rep = worm.verify(audit_dir=ad)
    assert rep["2020-01-01.ndjson"] == "ok"
    assert rep["2020-01-02.ndjson"] == "changed since push"
    assert rep["2020-01-03.ndjson"] == "NOT pushed"


# --- local sink -------------------------------------------------------------

def test_local_sink_writes_readonly_versioned(tmp_path):
    sink = worm.LocalWormSink(tmp_path / "worm")
    ru = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
    loc1 = sink.put("2020-01-01.ndjson", b"a", retain_until=ru)
    loc2 = sink.put("2020-01-01.ndjson", b"a2", retain_until=ru)
    p1, p2 = Path(loc1["path"]), Path(loc2["path"])
    assert p1 != p2 and p1.exists() and p2.exists()   # re-push kept the prior copy
    assert stat.S_IMODE(p1.stat().st_mode) == 0o444    # write-once on-box
    assert p1.read_bytes() == b"a" and p2.read_bytes() == b"a2"


def test_push_then_verify_through_local_sink(tmp_path):
    ad = _audit_dir(tmp_path, {"2020-01-01.ndjson": "a\n"})
    sink = worm.LocalWormSink(tmp_path / "store")
    worm.push_closed_dayfiles(audit_dir=ad, today="2025-01-01", sink=sink)
    assert worm.verify(audit_dir=ad) == {"2020-01-01.ndjson": "ok"}


# --- s3 sink (boto3 mocked) -------------------------------------------------

def test_s3_sink_put_uses_object_lock(monkeypatch):
    calls = {}

    class _FakeS3:
        def put_object(self, **kw):
            calls.update(kw)

    class _FakeBoto3:
        @staticmethod
        def client(*a, **k):
            return _FakeS3()

    monkeypatch.setitem(__import__("sys").modules, "boto3", _FakeBoto3)
    sink = worm.S3WormSink(bucket="b", prefix="audit/", mode="compliance")
    ru = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
    loc = sink.put("2020-01-01.ndjson", b"data", retain_until=ru)
    assert calls["Bucket"] == "b"
    assert calls["Key"] == "audit/2020-01-01.ndjson"
    assert calls["ObjectLockMode"] == "COMPLIANCE"
    assert calls["ObjectLockRetainUntilDate"] == ru
    assert loc["target"] == "s3" and loc["mode"] == "COMPLIANCE"


def test_s3_sink_rejects_bad_mode():
    with pytest.raises(worm.WormUnavailable):
        worm.S3WormSink(bucket="b", mode="whenever")


def test_worm_enabled_env_and_config(monkeypatch):
    monkeypatch.delenv("MAVERICK_AUDIT_WORM", raising=False)
    monkeypatch.setattr(worm, "_worm_cfg", dict)
    assert worm.worm_enabled() is False
    monkeypatch.setattr(worm, "_worm_cfg", lambda: {"provider": "s3"})
    assert worm.worm_enabled() is True
    monkeypatch.setenv("MAVERICK_AUDIT_WORM", "0")
    assert worm.worm_enabled() is False   # env wins


def test_push_refuses_unsealed_plaintext_when_sealing_active(tmp_path, monkeypatch):
    # Council H3: WORM must never lock PLAINTEXT audit data under a multi-year
    # immutable retention. When sealing is active (at-rest on + key present) an
    # unsealed closed day-file is refused until `audit seal` runs.
    ad = _audit_dir(tmp_path, {"2020-01-01.ndjson": "plaintext event\n"})
    monkeypatch.setattr(worm, "_at_rest_sealing_active", lambda: True)
    sink = FakeSink()
    rep = worm.push_closed_dayfiles(audit_dir=ad, today="2025-01-01", sink=sink)
    assert "refused: unsealed plaintext" in rep["2020-01-01.ndjson"]
    assert sink.puts == []   # nothing shipped


def test_push_allows_when_sealing_inactive(tmp_path, monkeypatch):
    # Inert when sealing can't run (no key / CI): we can't expect sealed files.
    ad = _audit_dir(tmp_path, {"2020-01-01.ndjson": "plaintext event\n"})
    monkeypatch.setattr(worm, "_at_rest_sealing_active", lambda: False)
    sink = FakeSink()
    rep = worm.push_closed_dayfiles(audit_dir=ad, today="2025-01-01", sink=sink)
    assert rep["2020-01-01.ndjson"] == "pushed"
    assert len(sink.puts) == 1
