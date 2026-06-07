"""Workspaces (tenants): per-business isolation of the factory's data."""
from __future__ import annotations

from pathlib import Path

from maverick.workspace import Workspace, _sanitize_tenant


class TestWorkspacePaths:
    def test_single_tenant_uses_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
        monkeypatch.delenv("MAVERICK_TENANT", raising=False)
        ws = Workspace.current()
        assert ws.tenant is None
        assert ws.root == tmp_path
        assert ws.domains_dir == tmp_path / "domains"

    def test_tenant_gets_its_own_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
        monkeypatch.setenv("MAVERICK_TENANT", "Acme Co")
        ws = Workspace.current()
        assert ws.tenant == "Acme Co"
        assert ws.root == tmp_path / "tenants" / "acme_co"
        assert ws.domains_dir == tmp_path / "tenants" / "acme_co" / "domains"
        assert ws.knowledge_path == tmp_path / "tenants" / "acme_co" / "knowledge.db"

    def test_two_tenants_are_separate(self):
        assert Workspace("alpha").root != Workspace("beta").root


class TestTenantSanitization:
    def test_path_traversal_cannot_escape(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
        ws = Workspace("../../etc")
        assert (tmp_path / "tenants") in ws.root.parents  # stays under the root
        assert ".." not in ws.root.parts                   # no traversal

    def test_sanitize_examples(self):
        assert _sanitize_tenant("Acme Co.") == "acme_co"
        assert _sanitize_tenant("../../etc") == "etc"
        assert _sanitize_tenant("a/b\\c") == "a_b_c"
        assert _sanitize_tenant("") == "default"


class TestPerTenantDomainIsolation:
    def test_domains_are_walled_off_by_tenant(self, tmp_path, monkeypatch):
        # A domain saved under tenant 'alpha' must not appear for tenant 'beta'.
        from maverick.domain import DomainProfile, available_domains
        from maverick.intake import save_profile

        monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
        monkeypatch.delenv("MAVERICK_DOMAINS_DIR", raising=False)

        monkeypatch.setenv("MAVERICK_TENANT", "alpha")
        save_profile(DomainProfile(name="alpha_only", persona="x"), approved=True)
        assert "alpha_only" in available_domains()  # visible to its own business

        monkeypatch.setenv("MAVERICK_TENANT", "beta")
        assert "alpha_only" not in available_domains()  # walled off from another

    def test_save_lands_under_the_tenant_root(self, tmp_path, monkeypatch):
        from maverick.domain import DomainProfile
        from maverick.intake import save_profile

        monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
        monkeypatch.delenv("MAVERICK_DOMAINS_DIR", raising=False)
        monkeypatch.setenv("MAVERICK_TENANT", "gamma")
        path = Path(save_profile(DomainProfile(name="g1", persona="x"), approved=True))
        assert (tmp_path / "tenants" / "gamma" / "domains") in path.parents
