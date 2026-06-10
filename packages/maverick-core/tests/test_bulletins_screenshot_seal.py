"""Safety bulletin RSS + tamper-evident screenshot seals."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest
from maverick.safety_bulletins import load_bulletins, parse_bulletin, render_rss
from maverick.screenshot_seal import (
    SealKeyMissing,
    seal,
    verify_file,
    verify_ledger,
)

BULLETIN = """---
id: MAV-2027-001
title: Sandbox escape via crafted args
severity: high
date: 2027-03-31
---

A crafted args array could bypass path confinement.

Details follow.
"""


# ---- bulletins ----

def test_parse_and_summary(tmp_path):
    p = tmp_path / "b1.md"
    p.write_text(BULLETIN)
    b = parse_bulletin(p)
    assert b.id == "MAV-2027-001" and b.severity == "high"
    assert b.summary.startswith("A crafted args array")


def test_load_orders_and_skips(tmp_path):
    (tmp_path / "old.md").write_text(BULLETIN.replace("2027-03-31", "2026-01-01")
                                     .replace("MAV-2027-001", "MAV-2026-001"))
    (tmp_path / "new.md").write_text(BULLETIN)
    (tmp_path / "bad.md").write_text("no frontmatter here")
    bulletins, skipped = load_bulletins(tmp_path)
    assert [b.id for b in bulletins] == ["MAV-2027-001", "MAV-2026-001"]
    assert skipped and "bad.md" in skipped[0]


def test_rss_is_valid_xml_with_items(tmp_path):
    (tmp_path / "b.md").write_text(BULLETIN)
    bulletins, _ = load_bulletins(tmp_path)
    xml = render_rss(bulletins, base_url="https://sec.example/bulletins")
    root = ET.fromstring(xml)
    assert root.tag == "rss"
    item = root.find("channel/item")
    assert item is not None
    assert "[HIGH]" in item.findtext("title")
    assert item.findtext("link") == "https://sec.example/bulletins/MAV-2027-001"
    assert item.findtext("guid") == "MAV-2027-001"


def test_rss_empty_feed_parses():
    assert ET.fromstring(render_rss([])).find("channel/item") is None


def test_bulletin_validation(tmp_path):
    bad = tmp_path / "x.md"
    bad.write_text("---\nid: A\ntitle: T\nseverity: enormous\ndate: 2027-01-01\n---\nbody")
    with pytest.raises(ValueError, match="severity"):
        parse_bulletin(bad)


# ---- screenshot seals ----

KEY = "seal-key"


def _capture(tmp_path, name="shot1.png", data=b"PNGDATA"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_seal_and_verify_valid(tmp_path):
    p = _capture(tmp_path)
    entry = seal(p, key=KEY)
    assert entry.prev == ""  # first in chain
    assert verify_file(p, key=KEY) == "VALID"


def test_modified_file_is_tampered(tmp_path):
    p = _capture(tmp_path)
    seal(p, key=KEY)
    p.write_bytes(b"DIFFERENT")
    assert verify_file(p, key=KEY) == "TAMPERED"


def test_unsealed_and_wrong_key(tmp_path):
    p = _capture(tmp_path)
    assert verify_file(p, key=KEY) == "UNSEALED"
    seal(p, key=KEY)
    assert verify_file(p, key="other-key") == "TAMPERED"


def test_chain_links_and_break_detection(tmp_path):
    p1 = _capture(tmp_path, "a.png", b"A")
    p2 = _capture(tmp_path, "b.png", b"B")
    seal(p1, key=KEY)
    e2 = seal(p2, key=KEY)
    assert e2.prev != ""
    report = verify_ledger(tmp_path, key=KEY)
    assert report["ok"] and report["entries"] == 2
    # Delete the first ledger line: chain breaks at index 0.
    ledger = tmp_path / ".seals.jsonl"
    lines = ledger.read_text().splitlines()
    ledger.write_text("\n".join(lines[1:]) + "\n")
    broken = verify_ledger(tmp_path, key=KEY)
    assert not broken["ok"] and broken["broken_at"] == 0


def test_ledger_detects_missing_and_modified(tmp_path):
    p1 = _capture(tmp_path, "a.png", b"A")
    p2 = _capture(tmp_path, "b.png", b"B")
    seal(p1, key=KEY)
    seal(p2, key=KEY)
    p1.unlink()
    p2.write_bytes(b"EDITED")
    report = verify_ledger(tmp_path, key=KEY)
    assert report["missing_files"] == ["a.png"]
    assert report["modified_files"] == ["b.png"]
    assert not report["ok"]


def test_recapture_supersedes(tmp_path):
    p = _capture(tmp_path, "a.png", b"V1")
    seal(p, key=KEY)
    p.write_bytes(b"V2")
    seal(p, key=KEY)  # legitimate re-capture
    report = verify_ledger(tmp_path, key=KEY)
    assert report["ok"]  # only the latest seal pins current bytes
    assert verify_file(p, key=KEY) == "VALID"


def test_missing_key_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("MAVERICK_SCREENSHOT_KEY", raising=False)
    import maverick.config as config_mod
    monkeypatch.setattr(config_mod, "load_config", lambda: {})
    p = _capture(tmp_path)
    with pytest.raises(SealKeyMissing):
        seal(p)


def test_entry_tamper_flagged(tmp_path):
    p = _capture(tmp_path)
    seal(p, key=KEY)
    ledger = tmp_path / ".seals.jsonl"
    entry = json.loads(ledger.read_text())
    entry["sha256"] = "0" * 64  # forge the hash without re-signing
    ledger.write_text(json.dumps(entry, sort_keys=True) + "\n")
    assert verify_file(p, key=KEY) == "TAMPERED"


def test_computer_screenshot_seals_when_key_set(tmp_path, monkeypatch):
    """The computer tool's screenshot path persists + seals when a key is set."""
    import base64 as _b64

    import maverick.paths as paths_mod
    import maverick.tools.computer as comp

    monkeypatch.setenv("MAVERICK_SCREENSHOT_KEY", KEY)
    monkeypatch.setattr(paths_mod, "data_dir",
                        lambda *parts, tenant="__active__": tmp_path.joinpath(*parts))
    png_b64 = _b64.b64encode(b"FAKEPNG").decode()
    comp._maybe_seal_capture(png_b64)
    captures = list((tmp_path / "captures").glob("*.png"))
    assert len(captures) == 1
    assert verify_file(captures[0], key=KEY) == "VALID"


def test_computer_screenshot_no_key_no_capture(tmp_path, monkeypatch):
    import base64 as _b64

    import maverick.config as config_mod
    import maverick.paths as paths_mod
    import maverick.tools.computer as comp

    monkeypatch.delenv("MAVERICK_SCREENSHOT_KEY", raising=False)
    monkeypatch.setattr(config_mod, "load_config", lambda: {})
    monkeypatch.setattr(paths_mod, "data_dir",
                        lambda *parts, tenant="__active__": tmp_path.joinpath(*parts))
    comp._maybe_seal_capture(_b64.b64encode(b"X").decode())
    assert not (tmp_path / "captures").exists()
