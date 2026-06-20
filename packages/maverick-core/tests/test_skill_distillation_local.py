"""Local skill distillation (ROADMAP 2028 H2)."""
from __future__ import annotations

from maverick.skill.distillation_local import (
    distill,
    distill_and_save,
    save_skill,
    to_skill_markdown,
)
from maverick.skills import validate_skill_file

_TRAJ = [
    {"goal": "Research competitor pricing and summarize findings", "success": True,
     "tools": ["web_search", "http_fetch"], "t": 100},
    {"goal": "Research market pricing trends and summarize them", "success": True,
     "tools": ["web_search", "write_file"], "t": 200},
    {"goal": "Delete the production database", "success": False, "tools": ["shell"], "t": 300},
]


def test_distill_picks_successful_recent():
    skill = distill(_TRAJ)
    assert skill is not None
    # name derived from frequent keywords (research/pricing/summarize)
    assert "research" in skill["name"] or "pricing" in skill["name"]
    assert len(skill["triggers"]) >= 1
    # tools unioned from successful runs only (no 'shell' from the failed one)
    assert "web_search" in skill["tools_needed"]
    assert "shell" not in skill["tools_needed"]


def test_distill_none_when_no_success():
    assert distill([{"goal": "x", "success": False, "tools": [], "t": 1}]) is None
    assert distill([]) is None


def test_name_is_kebab_case():
    skill = distill(_TRAJ)
    import re
    assert re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", skill["name"])


def test_generated_skill_is_valid(tmp_path):
    skill = distill(_TRAJ)
    path = save_skill(skill, tmp_path)
    assert path.exists()
    result = validate_skill_file(path)
    assert result.ok, f"distilled skill failed validation: {result.errors}"


def test_to_markdown_has_frontmatter():
    md = to_skill_markdown(distill(_TRAJ))
    assert md.startswith("---\nname: ")
    assert "triggers:" in md and "# Steps" in md


def test_to_markdown_carries_provenance():
    # A learned skill records WHEN it was learned, from how many examples, and
    # by which path -- so it is inspectable/auditable (governed learning).
    md = to_skill_markdown({**distill(_TRAJ), "distilled_at": "2026-01-02T03:04:05Z"})
    assert "distilled_at: 2026-01-02T03:04:05Z" in md  # injected timestamp round-trips
    assert "n_examples: 2" in md                        # 2 successful trajectories
    assert "source: auto-distilled-local-v2" in md


def test_provenance_round_trips_and_validates(tmp_path):
    # Provenance frontmatter must break neither the validator nor the parser.
    from maverick.skills import Skill
    skill = {**distill(_TRAJ), "distilled_at": "2026-01-02T03:04:05Z"}
    path = save_skill(skill, tmp_path)
    assert validate_skill_file(path).ok
    parsed = Skill.parse(path.read_text(encoding="utf-8"), path)
    assert parsed.name == skill["name"]  # known fields parse; provenance ignored in-memory


def test_distill_and_save_roundtrip(tmp_path):
    path = distill_and_save(_TRAJ, store=tmp_path)
    assert path is not None and path.exists()
    assert distill_and_save([], store=tmp_path) is None
