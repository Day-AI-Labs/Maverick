"""Intake generation core: LLM-pluggable pack generation, the safety clamp,
approved persistence, and document ingestion."""
from __future__ import annotations

import pytest
from maverick.domain import DomainProfile, load_domain
from maverick.intake import (
    IntakeSpec,
    generate_profile,
    ingest_docs,
    save_profile,
    validate_profile,
)


class TestValidateClamp:
    def test_caps_risk_and_denies_dangerous_tools(self):
        p = DomainProfile(name="x", allow_tools=["read_file", "shell", "code_exec"],
                          max_risk="high")
        validate_profile(p)
        assert p.max_risk == "medium"        # capped down from high
        assert "shell" in p.deny_tools       # baseline deny unioned in
        assert "shell" not in p.allow_tools  # stripped from allow
        assert "code_exec" not in p.allow_tools
        assert "read_file" in p.allow_tools  # safe tool kept
        assert p.authoring == "generated"


class TestGenerate:
    def test_dangerous_proposal_is_clamped(self):
        spec = IntakeSpec(name="Acme Capital", description="a hedge fund")

        def propose(_s):  # an over-eager proposer asks for shell + high risk
            return {"persona": "trade freely", "allow_tools": ["read_file", "shell"],
                    "max_risk": "high"}

        prof = generate_profile(spec, propose=propose)
        assert prof.name == "acme_capital"
        assert prof.compartment == "acme_capital"
        assert prof.max_risk == "medium"
        assert "shell" not in prof.allow_tools
        assert prof.knowledge_sources == ["acme_capital"]

    def test_default_when_no_proposer(self):
        prof = generate_profile(IntakeSpec(name="Beta LLC", industry="logistics"))
        assert prof.name == "beta_llc"
        assert prof.persona  # a default persona is synthesized
        assert prof.authoring == "generated"
        assert prof.max_risk == "medium"

    def test_proposer_failure_falls_back(self):
        def boom(_s):
            raise RuntimeError("model error")

        prof = generate_profile(IntakeSpec(name="Gamma"), propose=boom)
        assert prof.name == "gamma"
        assert prof.allow_tools  # safe default envelope, despite the failure


class TestSaveAndRoundtrip:
    def test_unapproved_is_refused(self, tmp_path):
        prof = generate_profile(IntakeSpec(name="Delta"))
        with pytest.raises(PermissionError):
            save_profile(prof, approved=False, dest_dir=tmp_path)

    def test_approved_roundtrips(self, tmp_path):
        prof = generate_profile(IntakeSpec(name="Epsilon Health",
                                           description="a clinic"))
        path = save_profile(prof, approved=True, dest_dir=tmp_path)
        reloaded = load_domain(path)
        assert reloaded.name == "epsilon_health"
        assert reloaded.compartment == "epsilon_health"
        assert reloaded.persona == prof.persona
        assert reloaded.max_risk == "medium"
        assert "shell" in reloaded.deny_tools


class TestIngestDocs:
    def test_ingests_uploaded_files(self, tmp_path):
        from maverick_knowledge import DeterministicEmbedder, KnowledgeBase

        doc = tmp_path / "policy.txt"
        doc.write_text("Our refund window is thirty days from purchase.")
        spec = IntakeSpec(name="Zeta Co", doc_paths=[str(doc)])
        kb = KnowledgeBase(embedder=DeterministicEmbedder(dim=64))
        assert ingest_docs(spec, kb) >= 1
        hits = kb.search("zeta_co", "refund window", k=3)
        assert hits and "refund" in hits[0].text.lower()


class _StubLLM:
    def __init__(self, text):
        self._text = text

    def complete(self, system, messages, **kw):
        from types import SimpleNamespace
        return SimpleNamespace(text=self._text)


class TestLLMProposer:
    def test_parse_plain_and_fenced_json(self):
        from maverick.intake import _parse_proposal
        assert _parse_proposal('{"persona": "hi", "max_risk": "low"}') == {
            "persona": "hi", "max_risk": "low"}
        fenced = '```json\n{"persona": "x", "allow_tools": ["read_file"]}\n```'
        out = _parse_proposal(fenced)
        assert out["persona"] == "x" and out["allow_tools"] == ["read_file"]

    def test_parse_junk_returns_empty(self):
        from maverick.intake import _parse_proposal
        assert _parse_proposal("sorry, I can't do that") == {}
        assert _parse_proposal("") == {}

    def test_llm_proposal_is_clamped_through_generation(self):
        from maverick.intake import build_llm_proposer
        llm = _StubLLM('{"persona": "You are a tax expert.", '
                       '"allow_tools": ["read_file", "shell"], "max_risk": "high"}')
        prof = generate_profile(IntakeSpec(name="Tax Co"),
                                propose=build_llm_proposer(llm))
        assert "tax expert" in prof.persona
        assert prof.max_risk == "medium"        # clamped from the LLM's "high"
        assert "shell" not in prof.allow_tools  # clamped despite the model asking


class TestRunIntake:
    def test_ingests_and_generates(self, tmp_path):
        from maverick.intake import run_intake
        from maverick_knowledge import DeterministicEmbedder, KnowledgeBase
        doc = tmp_path / "handbook.txt"
        doc.write_text("Employees accrue paid leave monthly.")
        kb = KnowledgeBase(embedder=DeterministicEmbedder(dim=64))
        llm = _StubLLM('{"persona": "HR helper", "allow_tools": ["read_file"]}')
        prof = run_intake(IntakeSpec(name="Theta Inc", doc_paths=[str(doc)]),
                          llm=llm, kb=kb)
        assert prof.name == "theta_inc"
        assert "HR helper" in prof.persona
        assert kb.search("theta_inc", "paid leave", k=3)  # docs were ingested


class TestIntakeSession:
    def test_records_and_finalizes(self, tmp_path):
        from maverick.intake import IntakeSession
        from maverick_knowledge import DeterministicEmbedder, KnowledgeBase
        doc = tmp_path / "faq.txt"
        doc.write_text("Returns are accepted within thirty days.")
        s = IntakeSession()
        assert s.is_ready() is False
        s.name = "Iota Retail"
        s.description = "an online store"
        s.goals.append("answer customer questions")
        s.doc_paths.append(str(doc))
        assert s.is_ready() is True
        assert s.to_spec().goals == ["answer customer questions"]

        kb = KnowledgeBase(embedder=DeterministicEmbedder(dim=64))
        prof = s.finalize(
            llm=_StubLLM('{"persona": "store helper", "allow_tools": ["read_file"]}'),
            kb=kb,
        )
        assert prof.name == "iota_retail"
        assert "store helper" in prof.persona
        assert prof.max_risk == "medium"
        assert kb.search("iota_retail", "returns", k=3)  # ingested on finalize
