"""Pack output contract: the *consumption* side of a domain pack -- what the
specialist delivers, to whom, how often, and what sign-off it needs. Additive
to the schema, so a pack without an ``[output]`` block behaves exactly as
before (a prose result with no declared consumer)."""
from __future__ import annotations

from maverick.domain import (
    DomainProfile,
    OutputContract,
    _coerce_output,
    available_domains,
    lint_profile,
    load_domain,
    overlay_profile,
)


class TestOutputSchema:
    def test_absent_block_is_empty_prose_contract(self, tmp_path):
        # The default: no [output] => today's behaviour, a prose deliverable.
        f = tmp_path / "p.toml"
        f.write_text('name = "p"\nallow_tools = ["read_file"]\n')
        prof = load_domain(f)
        assert prof.output == OutputContract()
        assert prof.output.shape == "prose"
        assert prof.output.consumers == []
        assert prof.output.gate is None

    def test_loads_output_block_from_toml(self, tmp_path):
        f = tmp_path / "p.toml"
        f.write_text(
            'name = "p"\n'
            'allow_tools = ["read_file"]\n'
            '[output]\n'
            'shape = "forecast"\n'
            'deliverable = "13-week cash forecast"\n'
            'consumers = ["fpa_analyst", "treasurer"]\n'
            'cadence = "weekly"\n'
            'gate = "review"\n'
        )
        out = load_domain(f).output
        assert out.shape == "forecast"
        assert out.deliverable == "13-week cash forecast"
        assert out.consumers == ["fpa_analyst", "treasurer"]
        assert out.cadence == "weekly"
        assert out.gate == "review"

    def test_coerce_is_forgiving(self):
        # Non-table => empty; stray non-list consumers => []; missing keys default.
        assert _coerce_output("nonsense") == OutputContract()
        out = _coerce_output({"shape": "table", "consumers": "fpa"})
        assert out.shape == "table"
        assert out.consumers == []          # a string is not a list of roles
        assert out.deliverable == ""        # missing key defaults
        assert out.gate is None

    def test_malformed_output_does_not_break_discovery(self, tmp_path):
        # A scalar where a table is expected must not raise at load time.
        f = tmp_path / "p.toml"
        f.write_text('name = "p"\nallow_tools = ["read_file"]\noutput = "oops"\n')
        prof = load_domain(f)             # must not raise
        assert prof.output == OutputContract()


class TestOutputOverlay:
    def test_overlay_preserves_base_contract(self):
        # Overlaying an unrelated field must NOT wipe the base's deliverable.
        base = DomainProfile(
            name="x", allow_tools=["read_file"], max_risk="low",
            output=OutputContract(shape="forecast", deliverable="cash forecast",
                                  consumers=["fpa_analyst"]),
        )
        merged = overlay_profile(base, {"description": "Tuned for ACME."})
        assert merged.description == "Tuned for ACME."          # patched
        assert merged.output.shape == "forecast"                # inherited
        assert merged.output.deliverable == "cash forecast"     # inherited
        assert merged.output.consumers == ["fpa_analyst"]       # inherited

    def test_overlay_can_patch_output(self):
        base = DomainProfile(name="x", allow_tools=["read_file"],
                             output=OutputContract(shape="prose"))
        merged = overlay_profile(base, {"output": {"shape": "report",
                                                   "consumers": ["risk_officer"]}})
        assert merged.output.shape == "report"
        assert merged.output.consumers == ["risk_officer"]


class TestLintOutput:
    def _ok_base(self, **kw):
        return DomainProfile(
            name="x", persona="x" * 250, allow_tools=["read_file"],
            deny_tools=["shell"], max_risk="low", knowledge_sources=["x"],
            description="d", **kw,
        )

    def test_valid_contract_has_no_output_warning(self):
        p = self._ok_base(output=OutputContract(
            shape="forecast", deliverable="cash forecast",
            consumers=["fpa_analyst"], gate="review"))
        _, warnings = lint_profile(p)
        assert not any("output" in w for w in warnings)

    def test_unknown_shape_warns(self):
        p = self._ok_base(output=OutputContract(shape="hologram"))
        _, warnings = lint_profile(p)
        assert any("output.shape" in w for w in warnings)

    def test_unknown_gate_warns(self):
        p = self._ok_base(output=OutputContract(deliverable="d",
                                                consumers=["x"], gate="rubber-stamp"))
        _, warnings = lint_profile(p)
        assert any("output.gate" in w for w in warnings)

    def test_deliverable_without_consumers_warns(self):
        p = self._ok_base(output=OutputContract(deliverable="a report"))
        _, warnings = lint_profile(p)
        assert any("no consumers" in w for w in warnings)


class TestBuiltinContract:
    def test_finance_cash13w_declares_its_deliverable(self):
        # The proof pack: the 13-week cash forecast declares its consumption side.
        out = available_domains()["finance_cash13w"].output
        assert out.shape == "forecast"
        assert out.deliverable == "13-week cash forecast"
        assert "fpa_analyst" in out.consumers
        assert out.cadence == "weekly"
        assert out.gate == "review"
