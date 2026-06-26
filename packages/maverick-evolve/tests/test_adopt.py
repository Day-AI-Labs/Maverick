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


def test_inplace_adoption_preserves_original_in_bak(tmp_path):
    # With the default out_dir the pack is edited in place. The .bak must always
    # hold the PRISTINE original, even after adopting repeatedly -- a second
    # adoption must NOT clobber the original backup with the first adopted copy
    # (which used to make the shipped pack unrecoverable).
    apath, pack = _setup(tmp_path, {"persona": "V1 persona."})
    original = pack.read_text(encoding="utf-8")
    bak = pack.with_suffix(".toml.bak")

    # First in-place adoption: pack -> V1, .bak = original.
    assert adopt_best(apath, pack) == pack
    assert bak.read_text(encoding="utf-8") == original

    # New best, second in-place adoption: pack -> V2, .bak STILL = the original.
    archive = Archive.load(apath)
    archive.add(Candidate(config={"persona": "V2 persona."}, score=0.99))
    archive.save(apath)
    assert adopt_best(apath, pack) == pack
    assert tomllib.loads(pack.read_text(encoding="utf-8"))["persona"] == "V2 persona."
    assert bak.read_text(encoding="utf-8") == original  # original still recoverable


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


def test_concurrent_adopt_keeps_one_bak_and_no_temp(tmp_path):
    """The .bak guard (exists() and not bak.exists()) was a TOCTOU and the write
    used a fixed ".tmp"; serialized under a lock, concurrent adoptions leave the
    dest valid, exactly one .bak, and no temp residue."""
    import threading

    apath, pack = _setup(tmp_path, {
        "persona": "You are a SOX specialist; verify evidence twice.",
    })
    out = tmp_path / "out"
    n = 10

    def worker():
        adopt_best(apath, pack, out_dir=out)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    dest = out / pack.name
    assert dest.exists() and "SOX specialist" in dest.read_text()
    assert (out / (pack.name + ".bak")).exists()
    assert list(out.glob("*.tmp")) == []
