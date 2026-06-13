"""Per-client role customization: the editable system-prompt addendum, its
validation, persistence, and the merged view the dashboard renders."""
from __future__ import annotations

import pytest
from maverick.role_edit import (
    ROLES,
    list_roles,
    remove_role_override,
    resolved_role,
    role_addendum,
    validate_role,
    write_role_override,
)


@pytest.fixture(autouse=True)
def _roles_file(tmp_path, monkeypatch):
    """Redirect role overrides at a temp file (never touch the real workspace)."""
    monkeypatch.setenv("MAVERICK_ROLES_FILE", str(tmp_path / "roles.toml"))
    return tmp_path / "roles.toml"


class TestAddendum:
    def test_absent_by_default(self):
        assert role_addendum("orchestrator") == ""

    def test_write_then_read_round_trips(self, _roles_file):
        write_role_override("orchestrator", {"system_addendum": "Lead with risk."})
        assert role_addendum("orchestrator") == "Lead with risk."
        assert _roles_file.is_file()

    def test_multiple_roles_coexist(self):
        write_role_override("coder", {"system_addendum": "Prefer small diffs."})
        write_role_override("writer", {"system_addendum": "Use plain English."})
        assert role_addendum("coder") == "Prefer small diffs."
        assert role_addendum("writer") == "Use plain English."

    def test_unknown_role_has_no_addendum(self):
        # A domain specialist (role = pack name) never matches a known role.
        assert role_addendum("finance_ap_recon") == ""


class TestValidation:
    def test_unknown_role_rejected(self):
        assert validate_role("not_a_role", {"system_addendum": "x"})
        with pytest.raises(ValueError):
            write_role_override("not_a_role", {"system_addendum": "x"})

    def test_overlong_addendum_rejected(self):
        errors = validate_role("coder", {"system_addendum": "x" * 5000})
        assert any("too long" in e for e in errors)
        with pytest.raises(ValueError):
            write_role_override("coder", {"system_addendum": "x" * 5000})

    def test_valid_addendum_passes(self):
        assert validate_role("coder", {"system_addendum": "ok"}) == []


class TestLifecycle:
    def test_empty_addendum_clears_override(self):
        write_role_override("analyst", {"system_addendum": "temp"})
        assert role_addendum("analyst") == "temp"
        write_role_override("analyst", {"system_addendum": "   "})  # whitespace = clear
        assert role_addendum("analyst") == ""

    def test_remove_reverts(self):
        write_role_override("revisor", {"system_addendum": "double-check math"})
        assert remove_role_override("revisor") is True
        assert role_addendum("revisor") == ""
        assert remove_role_override("revisor") is False  # already gone


class TestViews:
    def test_resolved_role_unknown_is_none(self):
        assert resolved_role("nope") is None

    def test_resolved_role_reports_provenance_and_model(self):
        view = resolved_role("orchestrator")
        assert view["role"] == "orchestrator"
        assert view["is_override"] is False
        assert view["model"]  # a default model resolves
        write_role_override("orchestrator", {"system_addendum": "ACME first."})
        view = resolved_role("orchestrator")
        assert view["is_override"] is True
        assert view["system_addendum"] == "ACME first."

    def test_list_roles_covers_known_roles_and_flags_overrides(self):
        names = {r["role"] for r in list_roles()}
        assert {"orchestrator", "coder", "researcher"} <= names
        assert names == set(ROLES)
        write_role_override("coder", {"system_addendum": "small diffs"})
        flagged = {r["role"]: r["is_override"] for r in list_roles()}
        assert flagged["coder"] is True
        assert flagged["orchestrator"] is False
