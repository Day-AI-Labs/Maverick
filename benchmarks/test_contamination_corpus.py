"""Contamination guard: loadable leaked-brief corpus + empty-corpus
advisory (#320).

Previously _KNOWN_LEAKED_BRIEFS was an empty literal, so the
brief-in-corpus check silently always passed. Now the corpus loads from an
external file, and an empty corpus surfaces as an explicit low-severity
flag rather than looking 'clean'.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture
def guard():
    """The guard module, with its module-level corpus state reset before
    each test so the load-once cache doesn't leak across tests."""
    from _common import contamination_guard as mod
    mod._KNOWN_LEAKED_BRIEFS.clear()
    mod._CORPUS_LOADED = False
    yield mod
    mod._KNOWN_LEAKED_BRIEFS.clear()
    mod._CORPUS_LOADED = False


def test_empty_corpus_surfaces_advisory(guard, monkeypatch, tmp_path):
    # Point at a non-existent corpus file -> empty -> advisory flag.
    monkeypatch.setenv("MAVERICK_LEAKED_BRIEFS_FILE", str(tmp_path / "nope.txt"))
    flags = guard.check(task_id="t1", brief="some task brief", predicted_patch="x")
    kinds = {f.kind for f in flags}
    assert "leaked_corpus_unavailable" in kinds
    # The advisory is low severity (informational, not a contamination hit).
    advisory = next(f for f in flags if f.kind == "leaked_corpus_unavailable")
    assert advisory.severity == "low"


def test_loaded_corpus_flags_known_brief(guard, monkeypatch, tmp_path):
    import hashlib
    brief = "fix the flaky cache eviction test"
    h = hashlib.sha256(brief.strip().encode("utf-8")).hexdigest()[:16]
    corpus = tmp_path / "leaked.txt"
    corpus.write_text(f"# leaked briefs\n{h}\n", encoding="utf-8")
    monkeypatch.setenv("MAVERICK_LEAKED_BRIEFS_FILE", str(corpus))

    flags = guard.check(task_id="t1", brief=brief, predicted_patch="x")
    kinds = {f.kind for f in flags}
    assert "brief_in_leaked_corpus" in kinds
    # When the corpus IS loaded, the "unavailable" advisory must not fire.
    assert "leaked_corpus_unavailable" not in kinds


def test_loaded_corpus_clean_brief_no_flag(guard, monkeypatch, tmp_path):
    corpus = tmp_path / "leaked.txt"
    corpus.write_text("deadbeefdeadbeef\n", encoding="utf-8")  # some other hash
    monkeypatch.setenv("MAVERICK_LEAKED_BRIEFS_FILE", str(corpus))

    flags = guard.check(task_id="t1", brief="a totally novel brief", predicted_patch="x")
    kinds = {f.kind for f in flags}
    assert "brief_in_leaked_corpus" not in kinds
    assert "leaked_corpus_unavailable" not in kinds  # corpus is non-empty


def test_verbatim_gold_patch_still_flags(guard, monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_LEAKED_BRIEFS_FILE", str(tmp_path / "nope.txt"))
    flags = guard.check(
        task_id="t1", brief="b", predicted_patch="PATCH", gold_patch="PATCH",
    )
    assert any(f.kind == "verbatim_gold_patch" for f in flags)


def test_add_known_leaked_brief_runtime(guard, monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_LEAKED_BRIEFS_FILE", str(tmp_path / "nope.txt"))
    brief = "runtime-added brief"
    guard.add_known_leaked_brief(brief)
    flags = guard.check(task_id="t1", brief=brief, predicted_patch="x")
    assert any(f.kind == "brief_in_leaked_corpus" for f in flags)
