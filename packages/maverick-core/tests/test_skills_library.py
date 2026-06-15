"""The shipped cross-cutting + suite SKILL.md library: every skill validates.

The agent roster shipped 1,000+ domain packs while the SKILL.md library was a
single example -- the gap the expansion council flagged as highest-leverage.
This pins the library (``<repo>/skills/*.md``) to the same publish-readiness bar
the install/distill paths enforce (``maverick.skills.validate_skill_file``):
kebab name, at least one trigger, a real body, no embedded secrets. A new skill
that regresses any of those fails here before it can ship.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from maverick.skills import validate_skill_file

# packages/maverick-core/tests/ -> repo root is parents[3].
_SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
_FILES = sorted(_SKILLS_DIR.glob("*.md"))


def test_skills_library_present():
    # The council shipped 20 cross-cutting + 41 suite-specific skills.
    assert len(_FILES) >= 60, f"expected >=60 skills, found {len(_FILES)} in {_SKILLS_DIR}"


@pytest.mark.parametrize("path", _FILES, ids=[p.stem for p in _FILES])
def test_skill_validates(path):
    result = validate_skill_file(path)
    assert result.ok, f"{path.name}: {result.errors}"


@pytest.mark.parametrize("path", _FILES, ids=[p.stem for p in _FILES])
def test_skill_filename_is_its_kebab_name(path):
    # The filename stem is the canonical name, so load_skills + the index agree.
    parts = path.read_text(encoding="utf-8").split("---", 2)
    meta = parts[1] if len(parts) >= 3 else ""
    m = re.search(r"(?m)^name:\s*(\S+)", meta)
    assert m, f"{path.name}: no 'name:' in frontmatter"
    assert m.group(1) == path.stem, f"{path.name}: name {m.group(1)!r} != filename stem"
