"""Skill management tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from maverick.skills import (
    Skill,
    _safe_name,
    install_skill,
    relevant_skills,
    remove_skill,
)

SKILL_BODY = (
    "---\n"
    "name: my-test-skill\n"
    "triggers:\n"
    "  - test thing\n"
    "  - try this\n"
    "tools_needed:\n"
    "  - shell\n"
    "---\n"
    "\n"
    "# What it does\n"
    "\n"
    "Testing skills installation.\n"
)


class TestSafeName:
    def test_simple(self):
        assert _safe_name("my-skill") == "my-skill"

    def test_strips_special_chars(self):
        assert _safe_name("My Skill!") == "my-skill"

    def test_path_traversal_neutralized(self):
        # Slashes and dots get stripped -- no path escape via skill name.
        result = _safe_name("../etc/passwd")
        assert "/" not in result
        assert ".." not in result

    def test_empty_fallback(self):
        assert _safe_name("") == "skill"
        assert _safe_name("!!!") == "skill"


class TestInstallSkill:
    def test_from_local_path(self, tmp_path: Path):
        source = tmp_path / "my.md"
        source.write_text(SKILL_BODY)
        skills_dir = tmp_path / "skills"
        s = install_skill(str(source), skills_dir=skills_dir)
        assert s.name == "my-test-skill"
        assert (skills_dir / "my-test-skill.md").exists()
        assert "test thing" in s.triggers

    def test_local_missing_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="does not exist"):
            install_skill(str(tmp_path / "nope.md"), skills_dir=tmp_path / "skills")

    def test_creates_skills_dir(self, tmp_path: Path):
        source = tmp_path / "x.md"
        source.write_text(SKILL_BODY)
        skills_dir = tmp_path / "deep" / "path" / "that" / "doesnt" / "exist"
        install_skill(str(source), skills_dir=skills_dir)
        assert skills_dir.is_dir()

    def test_http_url_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="insecure URL scheme"):
            install_skill("http://example.com/skill.md", skills_dir=tmp_path / "skills")

    def test_https_download_has_size_limit(self, tmp_path: Path):
        class FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, n: int = -1) -> bytes:
                return b"x" * (300 * 1024)

        # guarded_urlopen fetches through a custom opener (to revalidate
        # redirect hops against the SSRF guard), so patch the opener's open().
        with patch("urllib.request.OpenerDirector.open", return_value=FakeResp()):
            with pytest.raises(ValueError, match="too large"):
                install_skill("https://example.com/skill.md", skills_dir=tmp_path / "skills")


class TestRemoveSkill:
    def test_removes_existing(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "to-go.md").write_text(SKILL_BODY)
        assert remove_skill("to-go", skills_dir=skills_dir) is True
        assert not (skills_dir / "to-go.md").exists()

    def test_returns_false_when_missing(self, tmp_path: Path):
        assert remove_skill("never-installed", skills_dir=tmp_path / "skills") is False

    def test_name_sanitized(self, tmp_path: Path):
        # Even adversarial names can't escape the skills_dir.
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        outside = tmp_path / "outside.md"
        outside.write_text("important")
        # _safe_name strips '..' and '/', so this targets skills_dir/...md or similar
        remove_skill("../outside", skills_dir=skills_dir)
        assert outside.exists()  # not touched


class TestSkillParse:
    def test_missing_frontmatter_raises(self, tmp_path: Path):
        bad = tmp_path / "bad.md"
        bad.write_text("just text no frontmatter")
        with pytest.raises(ValueError, match="missing YAML frontmatter"):
            Skill.parse(bad.read_text(), bad)

    def test_parses_triggers(self, tmp_path: Path):
        path = tmp_path / "x.md"
        path.write_text(SKILL_BODY)
        s = Skill.parse(path.read_text(), path)
        assert s.triggers == ["test thing", "try this"]
        assert s.tools_needed == ["shell"]


class TestRelevantSkills:
    def _make_skill(self, name: str, triggers: list[str]) -> Skill:
        return Skill(
            name=name, triggers=triggers, tools_needed=[], body="", path=Path("/x"),
        )

    def test_word_overlap_scoring(self):
        s1 = self._make_skill("a", ["web search results"])
        s2 = self._make_skill("b", ["send email"])
        out = relevant_skills("please do a web search", [s1, s2])
        assert s1 in out
        assert s2 not in out

    def test_substring_bonus_ranks_higher(self):
        s1 = self._make_skill("a", ["deploy a new service"])
        s2 = self._make_skill("b", ["deploy something"])
        out = relevant_skills("deploy a new service today", [s1, s2])
        # s1's full-phrase match beats s2's partial overlap.
        assert out[0] == s1

    def test_max_n_caps_results(self):
        skills = [self._make_skill(f"s{i}", ["test trigger"]) for i in range(10)]
        out = relevant_skills("test trigger", skills, max_n=3)
        assert len(out) == 3
