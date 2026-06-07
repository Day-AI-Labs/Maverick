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
