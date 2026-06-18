"""Archive-best adoption into domain packs (operator-gated)."""
from __future__ import annotations

import pytest
from maverick_evolve.adopt import adopt_best, plan_adoption, render_pack
from maverick_evolve.archive import Archive, Candidate

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


PACK = '''name = "finance_sox"
description = "SOX control testing"
persona = "You are a meticulous control tester."
allow_tools = ["knowledge_search", "sql_query"]
max_risk = "low"
'''


def _setup(tmp_path, config):
    archive = Archive()
    archive.add(Candidate(config=config, score=0.9))
    apath = tmp_path / "archive.json"
    archive.save(apath)
    pack = tmp_path / "finance_sox.toml"
    pack.write_text(PACK, encoding="utf-8")
    return apath, pack


def test_plan_overlays_only_adoptable_keys(tmp_path):
    apath, pack = _setup(tmp_path, {
        "persona": "You are a SOX specialist; verify evidence twice.",
        "max_swarm_fanout": 8,           # not adoptable: ignored
    })
    adopted, changes = plan_adoption(apath, pack)
    assert set(changes) == {"persona"}
    assert adopted["persona"].startswith("You are a SOX specialist")
    assert adopted["allow_tools"] == ["knowledge_search", "sql_query"]
    assert "max_swarm_fanout" not in adopted


def test_capability_keys_are_refused(tmp_path):
    apath, pack = _setup(tmp_path, {"allow_tools": ["shell"]})
    with pytest.raises(ValueError, match="non-adoptable"):
        plan_adoption(apath, pack, keys=["allow_tools"])


def test_adopt_writes_valid_toml_and_backs_up(tmp_path):
    apath, pack = _setup(tmp_path, {"persona": "New persona."})
    out = tmp_path / "user-domains"
    dest = adopt_best(apath, pack, out_dir=out)
    assert dest is not None and dest.parent == out
    with open(dest, "rb") as f:
        data = tomllib.load(f)
    assert data["persona"] == "New persona."
    assert data["name"] == "finance_sox"
    # Second adoption with an unchanged best is a no-op...
    assert adopt_best(apath, pack, out_dir=out) is None
    # ...and re-adoption after a new best backs up the previous adopted pack.
    archive = Archive.load(apath)
    archive.add(Candidate(config={"persona": "Even newer."}, score=0.95))
    archive.save(apath)
    dest2 = adopt_best(apath, pack, out_dir=out)
    assert dest2 == dest
    assert dest.with_suffix(".toml.bak").exists()


def test_adopt_writes_atomically_no_temp_left(tmp_path):
    # The pack is written via a temp sibling + os.replace (matching
    # Archive.save) so a crash can't leave a half-written pack. After a clean
    # adoption no ``.tmp`` artifact should remain next to the destination.
    apath, pack = _setup(tmp_path, {"persona": "New persona."})
    out = tmp_path / "user-domains"
    dest = adopt_best(apath, pack, out_dir=out)
    assert dest is not None
    assert not dest.with_name(dest.name + ".tmp").exists()
    assert list(out.glob("*.tmp")) == []


def test_render_pack_roundtrips_tables(tmp_path):
    text = render_pack({
        "name": "x", "persona": 'line "quoted"\nsecond',
        "allow_tools": ["a", "b"], "models": {"orchestrator": "m1"},
    })
    data = tomllib.loads(text)
    assert data["models"] == {"orchestrator": "m1"}
    assert 'quoted' in data["persona"] and "\n" in data["persona"]
