"""Quality gate on skill distillation.

A distilled skill is recalled into every future run on a similar goal, so
a low-confidence "success" that gets written becomes a standing
instruction — the learning loop's poison vector. distill() now skips
writing when the run's verifier confidence is below a threshold, and
stamps the accepted confidence into the skill's frontmatter as provenance.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from maverick.blackboard import Blackboard
from maverick.skills import Skill, _stamp_confidence, distill


class _StubLLM:
    """Returns a fixed SKILL.md body; records whether it was called."""

    model = "fake:test"

    def __init__(self):
        self.called = 0

    def complete(self, system, messages, budget=None, max_tokens=2048,
                 model=None, **kw):
        self.called += 1
        from maverick.llm import LLMResponse
        body = (
            "---\n"
            "name: do-the-thing\n"
            "triggers:\n"
            "  - do the thing\n"
            "tools_needed:\n"
            "  - shell\n"
            "---\n\n"
            "# What this skill does\n\nThing.\n\n# Steps\n\n1. Act.\n"
        )
        return LLMResponse(text=body, thinking=None,
                           stop_reason="end_turn", tool_calls=[])


@pytest.fixture
def bb():
    b = Blackboard()
    b.post("a", "finding", "did the thing")
    return b


class TestQualityGate:
    def test_high_confidence_writes_skill(self, tmp_path: Path, bb):
        llm = _StubLLM()
        skill = distill("do the thing", "done", bb, llm,
                        skills_dir=tmp_path, confidence=0.95)
        assert skill is not None
        assert skill.name == "do-the-thing"
        assert (tmp_path / "do-the-thing.md").exists()
        assert llm.called == 1

    def test_low_confidence_skips_and_does_not_call_llm(self, tmp_path: Path, bb):
        llm = _StubLLM()
        skill = distill("do the thing", "done", bb, llm,
                        skills_dir=tmp_path, confidence=0.40)
        assert skill is None
        # Gate is checked BEFORE the (paid) distiller call.
        assert llm.called == 0
        assert list(tmp_path.glob("*.md")) == []

    def test_threshold_is_inclusive_boundary(self, tmp_path: Path, bb):
        # Exactly at the default min (0.75) should pass.
        skill = distill("do the thing", "done", bb, _StubLLM(),
                        skills_dir=tmp_path, confidence=0.75)
        assert skill is not None

    def test_env_overrides_threshold(self, tmp_path: Path, bb, monkeypatch):
        monkeypatch.setenv("MAVERICK_DISTILL_MIN_CONFIDENCE", "0.9")
        # 0.8 would pass the default 0.75 but not the raised 0.9.
        skill = distill("do the thing", "done", bb, _StubLLM(),
                        skills_dir=tmp_path, confidence=0.8)
        assert skill is None

    def test_explicit_min_confidence_arg_wins(self, tmp_path: Path, bb):
        skill = distill("do the thing", "done", bb, _StubLLM(),
                        skills_dir=tmp_path, confidence=0.5, min_confidence=0.4)
        assert skill is not None

    def test_default_confidence_preserves_always_write(self, tmp_path: Path, bb):
        # No confidence passed -> default 1.0 -> always writes (back-compat).
        skill = distill("do the thing", "done", bb, _StubLLM(),
                        skills_dir=tmp_path)
        assert skill is not None


class TestProvenanceStamp:
    def test_confidence_stamped_into_frontmatter(self, tmp_path: Path, bb):
        skill = distill("do the thing", "done", bb, _StubLLM(),
                        skills_dir=tmp_path, confidence=0.88)
        assert skill is not None
        text = (tmp_path / "do-the-thing.md").read_text()
        assert "distilled_confidence: 0.88" in text
        # And it round-trips through parse.
        assert skill.distilled_confidence == pytest.approx(0.88)

    def test_parse_defaults_confidence_to_one_when_absent(self, tmp_path: Path):
        p = tmp_path / "legacy.md"
        p.write_text(
            "---\nname: legacy\ntriggers:\n  - x\n---\n\n# Body\n\ntext\n"
        )
        s = Skill.parse(p.read_text(), p)
        assert s.distilled_confidence == 1.0


class TestStampHelper:
    def test_inserts_when_absent(self):
        out = _stamp_confidence("---\nname: x\n---\nbody", 0.5)
        assert "distilled_confidence: 0.50" in out
        assert out.startswith("---\ndistilled_confidence: 0.50\n")

    def test_replaces_when_present(self):
        text = "---\ndistilled_confidence: 0.10\nname: x\n---\nbody"
        out = _stamp_confidence(text, 0.99)
        assert "distilled_confidence: 0.99" in out
        assert "0.10" not in out

    def test_noop_without_frontmatter(self):
        assert _stamp_confidence("no frontmatter here", 0.5) == "no frontmatter here"
