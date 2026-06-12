"""Installing a skill must not silently clobber a different skill.

User-testing finding: two different frontmatter names can sanitize to the same
filename (e.g. "..." and "....." both -> "skill"), and the second install
silently overwrote the first with no warning -- data loss. A colliding install
is now refused; a same-name re-install (an update) still succeeds.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from maverick.skills import install_skill


def _write(tmp: Path, fname: str, name: str, body: str) -> str:
    src = tmp / fname
    src.write_text(f'---\nname: "{name}"\ntriggers:\n  - x\n---\n{body}\n')
    return str(src)


def test_colliding_different_skill_is_refused_not_clobbered(tmp_path: Path):
    skills = tmp_path / "skills"
    first = _write(tmp_path, "a.md", "...", "FIRST skill body")
    second = _write(tmp_path, "b.md", ".....", "SECOND skill body")  # also -> "skill.md"

    s1 = install_skill(first, skills_dir=skills)
    assert s1.path.name == "skill.md"
    assert "FIRST" in s1.path.read_text()

    with pytest.raises(ValueError, match="different skill already occupies"):
        install_skill(second, skills_dir=skills)
    # The first skill survived intact -- no silent clobber.
    assert "FIRST" in (skills / "skill.md").read_text()


def test_same_name_reinstall_updates(tmp_path: Path):
    skills = tmp_path / "skills"
    v1 = _write(tmp_path, "v1.md", "greety", "version one")
    install_skill(v1, skills_dir=skills)
    v2 = _write(tmp_path, "v2.md", "greety", "version two")
    s = install_skill(v2, skills_dir=skills)  # same name -> update, no error
    assert "version two" in s.path.read_text()
