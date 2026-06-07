"""Domain packs: schema, loader, and capability derivation (agent factory)."""
from __future__ import annotations

from maverick.domain import (
    DomainProfile,
    available_domains,
    load_domain,
    load_domains,
)


class TestDomainProfile:
    def test_compartment_defaults_to_name(self):
        assert DomainProfile(name="finance").compartment == "finance"

    def test_explicit_compartment_kept(self):
        p = DomainProfile(name="finance-ops", compartment="finance")
        assert p.compartment == "finance"

    def test_capability_envelope_from_profile(self):
        p = DomainProfile(
            name="finance", allow_tools=["read_file"],
            deny_tools=["create_order_instruction"], max_risk="medium",
        )
        cap = p.capability("agent:finance-1")
        assert cap.principal == "agent:finance-1"
        assert cap.permits("read_file") is True
        assert cap.permits("create_order_instruction") is False  # deny wins
        assert cap.permits("some_unlisted_tool") is False         # whitelist


class TestLoader:
    def test_load_domain_from_toml(self, tmp_path):
        f = tmp_path / "legal.toml"
        f.write_text(
            'name = "legal"\n'
            'persona = "You are a legal specialist."\n'
            'allow_tools = ["read_file", "web_search"]\n'
            'knowledge_sources = ["legal"]\n'
        )
        prof = load_domain(f)
        assert prof.name == "legal"
        assert "legal specialist" in prof.persona
        assert prof.allow_tools == ["read_file", "web_search"]
        assert prof.knowledge_sources == ["legal"]

    def test_unknown_keys_are_ignored(self, tmp_path):
        f = tmp_path / "x.toml"
        f.write_text('name = "x"\nfuture_key = "ignored"\n')
        assert load_domain(f).name == "x"  # must not raise

    def test_load_domains_skips_malformed(self, tmp_path):
        (tmp_path / "ok.toml").write_text('name = "ok"\n')
        (tmp_path / "bad.toml").write_text("not = valid = toml [[[")
        domains = load_domains(tmp_path)
        assert "ok" in domains
        assert "bad" not in domains

    def test_missing_dir_returns_empty(self, tmp_path):
        assert load_domains(tmp_path / "nope") == {}


class TestBuiltinPacks:
    def test_finance_reference_pack_ships(self):
        domains = available_domains()
        assert "finance" in domains
        fin = domains["finance"]
        assert fin.compartment == "finance"
        assert "Interactive_Brokers_IBKR" in fin.mcp_servers
        # The derived capability denies order placement (deny wins).
        assert fin.capability("agent:f1").permits("create_order_instruction") is False
