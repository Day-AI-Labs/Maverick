"""Per-client pack customization: serialize/validate/persist overrides + the
merged provenance view the dashboard editor renders."""
from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

import pytest
from maverick.domain import available_domains, builtin_dir, lint_profile, load_domains
from maverick.domain_edit import (
    list_agents,
    overlay_toml,
    read_override,
    remove_override,
    resolved_view,
    validate_override,
    write_override,
)


def _clean_builtin():
    for name, prof in sorted(load_domains(builtin_dir()).items()):
        if not lint_profile(prof)[0]:
            return name, prof
    raise AssertionError("no lint-error-clean built-in pack found")


@pytest.fixture
def tenant_dir(tmp_path, monkeypatch):
    """Point the workspace domains dir (where overrides live) at a temp dir."""
    monkeypatch.setenv("MAVERICK_DOMAINS_DIR", str(tmp_path))
    return tmp_path


class TestOverlayToml:
    def test_round_trips_through_loader(self):
        patch = {
            "name": "p",
            "persona": "Multi-line\npersona with \"quotes\".",
            "allow_tools": ["read_file", "sql_query"],
            "models": {"coder": "anthropic:claude-sonnet-4-6"},
            "workflow": [
                {"name": "gather", "instruction": "Collect.", "tools": ["read_file"]},
                {"name": "draft", "gate": "review"},
            ],
        }
        loaded = tomllib.loads(overlay_toml(patch))
        assert loaded["name"] == "p"
        assert loaded["persona"] == 'Multi-line\npersona with "quotes".'
        assert loaded["allow_tools"] == ["read_file", "sql_query"]
        assert loaded["models"] == {"coder": "anthropic:claude-sonnet-4-6"}
        assert [s["name"] for s in loaded["workflow"]] == ["gather", "draft"]
        assert loaded["workflow"][1]["gate"] == "review"

    def test_only_present_keys_written(self):
        loaded = tomllib.loads(overlay_toml({"name": "p", "description": "d"}))
        assert set(loaded) == {"name", "description"}

    def test_nameless_workflow_step_skipped(self):
        loaded = tomllib.loads(overlay_toml({"name": "p", "workflow": [{"instruction": "x"}]}))
        assert "workflow" not in loaded

    def test_output_contract_round_trips_through_loader(self):
        patch = {"name": "p", "output": {
            "shape": "forecast", "deliverable": "13-week cash forecast",
            "consumers": ["fpa_analyst", "treasurer"], "cadence": "weekly",
            "gate": "review"}}
        loaded = tomllib.loads(overlay_toml(patch))
        assert loaded["output"]["shape"] == "forecast"
        assert loaded["output"]["deliverable"] == "13-week cash forecast"
        assert loaded["output"]["consumers"] == ["fpa_analyst", "treasurer"]
        assert loaded["output"]["gate"] == "review"


class TestWriteOverride:
    def test_partial_override_inherits_base(self, tenant_dir):
        name, base = _clean_builtin()
        write_override(name, {"description": "Client ACME tuning."})
        merged = available_domains()[name]
        assert merged.description == "Client ACME tuning."   # patched
        assert merged.allow_tools == base.allow_tools         # inherited
        assert (tenant_dir / f"{name}.toml").is_file()

    def test_rejects_override_that_fails_lint(self, tenant_dir):
        # A brand-new standalone pack with no allow_tools / no max_risk: the
        # merged result has lint errors, so the write must be refused.
        with pytest.raises(ValueError):
            write_override("nope", {"persona": "x" * 250})

    def test_workflow_edit_persists_and_drives_view(self, tenant_dir):
        name, _ = _clean_builtin()
        write_override(name, {"workflow": [
            {"name": "intake", "instruction": "Read the request."},
            {"name": "answer", "instruction": "Ground in docs and cite."},
        ]})
        view = resolved_view(name)
        assert [s["name"] for s in view["workflow"]] == ["intake", "answer"]
        assert "workflow" in view["overridden"]


class TestResolvedView:
    def test_builtin_has_no_override(self, tenant_dir):
        name, _ = _clean_builtin()
        view = resolved_view(name)
        assert view["is_override"] is False
        assert view["overridden"] == []

    def test_override_marks_provenance(self, tenant_dir):
        name, _ = _clean_builtin()
        write_override(name, {"persona": "x" * 250})
        view = resolved_view(name)
        assert view["is_override"] is True
        assert view["overridden"] == ["persona"]

    def test_unknown_pack_returns_none(self, tenant_dir):
        assert resolved_view("does_not_exist_anywhere") is None

    def test_view_exposes_output_contract(self, tenant_dir):
        # The merged view carries the deliverable so the editor/API can render it.
        view = resolved_view("finance_cash13w")
        assert view["output"]["shape"] == "forecast"
        assert view["output"]["deliverable"] == "13-week cash forecast"
        assert "fpa_analyst" in view["output"]["consumers"]


class TestValidateAndList:
    def test_validate_surfaces_errors_without_writing(self, tenant_dir):
        errors, _ = validate_override("nope", {"persona": "x" * 250})
        assert errors                               # empty allow_tools etc.
        assert read_override("nope") == {}          # nothing was written

    def test_list_agents_flags_overrides(self, tenant_dir):
        name, _ = _clean_builtin()
        before = {a["name"]: a for a in list_agents()}
        assert before[name]["is_override"] is False
        write_override(name, {"description": "tuned"})
        after = {a["name"]: a for a in list_agents()}
        assert after[name]["is_override"] is True

    def test_remove_override_reverts_to_builtin(self, tenant_dir):
        name, base = _clean_builtin()
        write_override(name, {"description": "temporary tuning"})
        assert resolved_view(name)["is_override"] is True
        assert remove_override(name) is True
        assert resolved_view(name)["is_override"] is False
        assert available_domains()[name].description == base.description
