"""The shipped cross-cutting + suite SKILL.md library: validates and is wired.

The agent roster shipped 1,000+ domain packs while the SKILL.md library was a
single example -- the gap the expansion council flagged as highest-leverage.
This pins the library (``maverick/skills_builtin/*.md``) to the same
publish-readiness bar the install/distill paths enforce
(``maverick.skills.validate_skill_file``) AND proves it is actually loaded at
runtime via ``available_skills`` (the agent recall path), with the env opt-out
honored.
"""
from __future__ import annotations

import re

import pytest
from maverick.skills import (
    available_skills,
    builtin_skills_dir,
    load_builtin_skills,
    validate_skill_file,
)

_FILES = sorted(builtin_skills_dir().glob("*.md"))


def test_skills_library_present():
    # The council shipped 20 cross-cutting + 41 suite-specific skills.
    assert len(_FILES) >= 60, f"expected >=60 skills, found {len(_FILES)} in {builtin_skills_dir()}"


@pytest.mark.parametrize("path", _FILES, ids=[p.stem for p in _FILES])
def test_skill_validates(path):
    result = validate_skill_file(path)
    assert result.ok, f"{path.name}: {result.errors}"


@pytest.mark.parametrize("path", _FILES, ids=[p.stem for p in _FILES])
def test_skill_filename_is_its_kebab_name(path):
    # The filename stem is the canonical name, so load + the index agree.
    parts = path.read_text(encoding="utf-8").split("---", 2)
    meta = parts[1] if len(parts) >= 3 else ""
    m = re.search(r"(?m)^name:\s*(\S+)", meta)
    assert m, f"{path.name}: no 'name:' in frontmatter"
    assert m.group(1) == path.stem, f"{path.name}: name {m.group(1)!r} != filename stem"


def test_builtin_skills_load_when_enabled(monkeypatch, tmp_path):
    # The autouse conftest disables builtin skills; opt back in and confirm the
    # whole library is recalled through available_skills (the agent path).
    monkeypatch.setenv("MAVERICK_BUILTIN_SKILLS", "1")
    builtin = {s.name for s in load_builtin_skills()}
    assert len(builtin) >= 60
    avail = {s.name for s in available_skills(skills_dir=tmp_path / "empty-user-dir")}
    assert builtin <= avail, "available_skills must include the shipped library when enabled"


def test_builtin_skills_excluded_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_BUILTIN_SKILLS", "0")
    assert available_skills(skills_dir=tmp_path / "empty-user-dir") == []
