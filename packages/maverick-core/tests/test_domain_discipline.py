"""Suite operating discipline + department memory at specialist spawn."""
from __future__ import annotations

from maverick import domain_discipline, dreaming, reflexion
from maverick.domain import DomainProfile, _department_memory, lint_profile


class TestDiscipline:
    def test_every_suite_has_a_block(self):
        from maverick.domain import SUITE_PREFIXES
        assert set(domain_discipline.SUITE_DISCIPLINE) == set(
            SUITE_PREFIXES.values(),
        )

    def test_suite_pack_gets_universal_plus_suite(self):
        block = domain_discipline.discipline_for("finance_sox")
        assert "Operating discipline:" in block
        assert "segregation of duties" in block.lower()
        # And a different suite gets ITS discipline, not finance's.
        legal = domain_discipline.discipline_for("legal_settlement")
        assert "privilege" in legal.lower()
        assert "segregation of duties" not in legal.lower()

    def test_generic_pack_gets_universal_only(self):
        block = domain_discipline.discipline_for("generic")
        assert "Operating discipline:" in block
        assert "Finance discipline" not in block

    def test_augment_appends_and_respects_opt_out(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_DOMAIN_DISCIPLINE", raising=False)
        out = domain_discipline.augment_persona("finance_sox", "You are X.")
        assert out.startswith("You are X.")
        assert "Finance discipline" in out
        monkeypatch.setenv("MAVERICK_DOMAIN_DISCIPLINE", "0")
        assert domain_discipline.augment_persona(
            "finance_sox", "You are X.",
        ) == "You are X."


class TestSpawnIntegration:
    def _ctx(self, tmp_path):
        from maverick.blackboard import Blackboard
        from maverick.budget import Budget
        from maverick.sandbox import LocalBackend
        from maverick.swarm import SwarmContext
        from maverick.world_model import WorldModel

        world = WorldModel(tmp_path / "world.db")
        return SwarmContext(
            llm=None, world=world, budget=Budget(max_dollars=1.0),
            blackboard=Blackboard(), sandbox=LocalBackend(workdir=tmp_path),
            goal_id=world.create_goal("g", ""), use_skills=False,
        )

    def test_spawned_specialist_carries_discipline(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MAVERICK_DOMAIN_DISCIPLINE", raising=False)
        from maverick.domain import agent_from_profile
        profile = DomainProfile(
            name="finance_sox", persona="You are a SOX control tester.",
            allow_tools=["read_file"], max_risk="low",
        )
        agent = agent_from_profile(profile, self._ctx(tmp_path), "test controls")
        assert "You are a SOX control tester." in agent.system
        assert "Finance discipline" in agent.system
        assert "Operating discipline" in agent.system

    def test_department_memory_reaches_the_brief(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_REFLEXION", "1")
        monkeypatch.setattr(reflexion, "default_path",
                            lambda: tmp_path / "reflexions.ndjson")
        reflexion.record(
            goal_text="reconcile the quarterly ledger totals",
            failure_class="budget", failure_msg="cap",
            reflection="raise the cap before starting",
            domain="finance_sox",
        )
        from maverick.domain import agent_from_profile
        profile = DomainProfile(
            name="finance_sox", persona="You are a SOX control tester.",
            allow_tools=["read_file"], max_risk="low",
        )
        agent = agent_from_profile(
            profile, self._ctx(tmp_path), "reconcile the quarterly ledger",
        )
        assert "Prior failures on similar goals" in agent.brief
        assert "raise the cap" in agent.brief

    def test_department_memory_uses_run_scope_and_shield(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_REFLEXION", "1")
        monkeypatch.setattr(reflexion, "default_path",
                            lambda: tmp_path / "reflexions.ndjson")
        reflexion.record(
            goal_text="reconcile leaked operator ledger",
            failure_class="scope", failure_msg="unscoped",
            reflection="LEAKME_OPERATOR_SECRET",
            domain="finance_sox",
        )
        reflexion.record(
            goal_text="reconcile customer ledger",
            failure_class="scope", failure_msg="scoped",
            reflection="LEAKME_SCOPED_SECRET",
            channel="api", user_id="victim-user", domain="finance_sox",
        )

        class Verdict:
            allowed = False

        class Shield:
            def scan_input(self, text):
                if "LEAKME_SCOPED_SECRET" in text:
                    return Verdict()
                allowed = type("Allowed", (), {"allowed": True})
                return allowed()

        ctx = self._ctx(tmp_path)
        ctx.channel = "api"
        ctx.user_id = "victim-user"
        ctx.shield = Shield()

        from maverick.domain import agent_from_profile
        profile = DomainProfile(
            name="finance_sox", persona="You are a SOX control tester.",
            allow_tools=["read_file"], max_risk="low",
        )

        agent = agent_from_profile(profile, ctx, "reconcile customer ledger")

        assert "LEAKME_OPERATOR_SECRET" not in agent.brief
        assert "LEAKME_SCOPED_SECRET" not in agent.brief
        assert "[redacted by Shield]" in agent.brief

    def test_memory_block_empty_when_loops_disabled(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MAVERICK_REFLEXION", raising=False)
        monkeypatch.delenv("MAVERICK_DREAMING", raising=False)
        profile = DomainProfile(name="finance_sox")
        assert _department_memory(profile, "anything") == ""

    def test_memory_includes_dream_insights(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_DREAMING", "1")
        ipath = tmp_path / "insights.ndjson"
        dreaming.append_insights([dreaming.DreamInsight(
            ts=1.0, kind="failure_pattern", domain="finance_sox",
            text="Recurring failure (budget, seen 3x) on ledger goals.",
            evidence=3,
        )], path=ipath)
        monkeypatch.setattr(dreaming, "insights_path", lambda: ipath)
        profile = DomainProfile(name="finance_sox")
        memory = _department_memory(profile, "prepare the walkthrough memo")
        assert "Consolidated lessons" in memory


class TestLintProfile:
    def test_clean_pack_is_clean(self):
        errors, warnings = lint_profile(DomainProfile(
            name="finance_sox", description="SOX control testing",
            persona="x" * 250, allow_tools=["read_file"],
            deny_tools=["shell", "write_file"], max_risk="low",
            knowledge_sources=["finance"],
        ))
        assert errors == [] and warnings == []

    def test_empty_allowlist_and_bad_risk_are_errors(self):
        errors, _ = lint_profile(DomainProfile(name="x", max_risk="extreme"))
        assert any("ALL tools" in e for e in errors)
        assert any("extreme" in e for e in errors)
        errors2, _ = lint_profile(DomainProfile(name="x", allow_tools=["a"]))
        assert any("max_risk is unset" in e for e in errors2)

    def test_quality_gaps_are_warnings(self):
        _, warnings = lint_profile(DomainProfile(
            name="x", persona="short", allow_tools=["a", "b"],
            deny_tools=["b"], max_risk="low",
        ))
        joined = " ".join(warnings)
        assert "both allowed and denied" in joined
        assert "persona under" in joined
        assert "knowledge_sources" in joined

    def test_all_builtin_packs_pass_error_level(self):
        from maverick.domain import builtin_dir, load_domains
        for name, prof in load_domains(builtin_dir()).items():
            errors, _ = lint_profile(prof)
            assert errors == [], f"{name}: {errors}"
