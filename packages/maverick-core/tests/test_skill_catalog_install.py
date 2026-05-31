"""install_from_catalog: resolve by name, verify hash, then install."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from maverick import catalog, skills

_BODY = """---
name: summarize-url
triggers: ["summarize this url"]
tools_needed: ["http_fetch"]
---
# Summarize a URL

Fetch with http_fetch, write 3 sentences.
"""
_SHA = hashlib.sha256(_BODY.encode()).hexdigest()


def _entry(**over):
    d = {
        "name": "summarize-url", "version": "1.0.0",
        "summary": "x", "source": "gh:org/repo:SKILL.md",
        "sha256": _SHA, "author": "org", "verified": True,
    }
    d.update(over)
    return catalog.CatalogEntry.from_dict("skills", d)


def test_install_from_catalog_happy_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(catalog, "resolve", lambda name, kind, indexes=None: _entry())
    monkeypatch.setattr(skills, "_fetch_skill_source", lambda source: _BODY)
    s = skills.install_from_catalog("summarize-url", skills_dir=tmp_path)
    assert s.name == "summarize-url"
    assert (tmp_path / "summarize-url.md").exists()


def test_install_from_catalog_unknown_name(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(catalog, "resolve", lambda name, kind, indexes=None: None)
    with pytest.raises(ValueError, match="no catalog skill"):
        skills.install_from_catalog("nope", skills_dir=tmp_path)


def test_install_from_catalog_rejects_hash_mismatch(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(catalog, "resolve", lambda name, kind, indexes=None: _entry())
    # Source returns tampered content that won't match the pinned sha.
    monkeypatch.setattr(skills, "_fetch_skill_source", lambda source: "TAMPERED")
    with pytest.raises(ValueError, match="hash mismatch"):
        skills.install_from_catalog("summarize-url", skills_dir=tmp_path)
    # Nothing written.
    assert not list(tmp_path.glob("*.md"))


def test_install_from_catalog_rejects_unpinned_entry(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(catalog, "resolve",
                        lambda name, kind, indexes=None: _entry(sha256=""))
    monkeypatch.setattr(skills, "_fetch_skill_source", lambda source: _BODY)
    with pytest.raises(ValueError, match="hash mismatch"):
        skills.install_from_catalog("summarize-url", skills_dir=tmp_path)


def test_fetch_skill_source_rejects_local_path():
    with pytest.raises(ValueError, match="gh: or https:"):
        skills._fetch_skill_source("/etc/passwd")


def test_fetch_skill_source_rejects_http():
    with pytest.raises(ValueError):
        skills._fetch_skill_source("http://insecure/SKILL.md")


def test_example_index_sha_matches_committed_skill():
    """The committed example index must pin the real hash of its skill —
    catches drift if someone edits the example SKILL.md without updating
    the index."""
    import json
    root = Path(__file__).resolve().parents[3]
    idx_path = root / "docs" / "specs" / "catalog-example" / "skills" / "index.json"
    skill_path = root / "docs" / "specs" / "catalog-example" / "skills" / "summarize-url" / "SKILL.md"
    if not idx_path.exists() or not skill_path.exists():
        pytest.skip("example catalog not present")
    index = json.loads(idx_path.read_text())
    body = skill_path.read_text()
    pinned = index["entries"][0]["sha256"]
    actual = hashlib.sha256(body.encode()).hexdigest()
    assert pinned == actual, "example index sha256 drifted from the example SKILL.md"
