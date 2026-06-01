"""Plugin loader hardening (#463): dist-qualified allowlist (name-squat),
dedup-by-name, and semver-major manifest compatibility.
"""
from __future__ import annotations

from maverick import plugins
from maverick.plugin_manifest import MAVERICK_API_VERSION, parse_dict


class _FakeDist:
    def __init__(self, name):
        self.name = name


class _FakeEP:
    def __init__(self, name, dist_name=None):
        self.name = name
        self.dist = _FakeDist(dist_name) if dist_name else None


# ---------- is_compatible: semver-major, not string equality ----------

class TestIsCompatible:
    def test_bare_major_matches(self):
        m = parse_dict({"plugin": {"name": "p", "version": "0.1", "api_version": "1"}})
        assert m.is_compatible() is True

    def test_dotted_minor_matches_same_major(self):
        # '1.0' / '1.2.3' must be compatible with kernel major '1' (the old
        # string-equality marked these incompatible).
        for v in ("1.0", "1.2.3", "01"):
            m = parse_dict({"plugin": {"name": "p", "version": "0.1", "api_version": v}})
            assert m.is_compatible() is True, v

    def test_different_major_incompatible(self):
        m = parse_dict({"plugin": {"name": "p", "version": "0.1", "api_version": "2"}})
        assert m.is_compatible() is False
        assert any("api_version" in w for w in m.warnings)

    def test_unparseable_incompatible(self):
        m = parse_dict({"plugin": {"name": "p", "version": "0.1", "api_version": "abc"}})
        assert m.is_compatible() is False

    def test_kernel_version_is_major_1(self):
        # Guards the test's premise.
        assert MAVERICK_API_VERSION.split(".")[0] == "1"


# ---------- allowlist: dist-qualified (name-squat defense) ----------

class TestAllowlistQualification:
    def test_bare_name_allowed(self):
        ep = _FakeEP("weather", "trusted-weather")
        assert plugins._is_allowed(ep, {"weather"}) is True

    def test_wildcard_allows_all(self):
        ep = _FakeEP("weather", "anything")
        assert plugins._is_allowed(ep, None) is True

    def test_qualified_name_allowed(self):
        ep = _FakeEP("weather", "trusted-weather")
        assert plugins._is_allowed(ep, {"trusted-weather:weather"}) is True

    def test_qualified_mismatch_blocks_squatter(self):
        # An allowlist pinned to a specific dist must NOT match a different
        # dist that squats the same entry-point name.
        squatter = _FakeEP("weather", "evil-pkg")
        assert plugins._is_allowed(squatter, {"trusted-weather:weather"}) is False

    def test_not_in_allowlist(self):
        ep = _FakeEP("other", "x")
        assert plugins._is_allowed(ep, {"weather"}) is False


# ---------- dedup by entry-point name ----------

class TestEligibleDedup:
    def test_duplicate_names_deduped(self, monkeypatch):
        eps = [_FakeEP("dup", "dist-a"), _FakeEP("dup", "dist-b"),
               _FakeEP("unique", "dist-c")]
        monkeypatch.setattr(plugins, "_entry_points", lambda group: eps)
        monkeypatch.setattr(plugins, "_allowed_plugin_names", lambda: None)  # all
        got = list(plugins._eligible("maverick.tools", "tool"))
        names = [e.name for e in got]
        assert names == ["dup", "unique"]  # second 'dup' dropped
        # The kept one is the first (dist-a).
        assert got[0].dist.name == "dist-a"

    def test_dedup_respects_allowlist(self, monkeypatch):
        eps = [_FakeEP("a", "d1"), _FakeEP("b", "d2")]
        monkeypatch.setattr(plugins, "_entry_points", lambda group: eps)
        monkeypatch.setattr(plugins, "_allowed_plugin_names", lambda: {"a"})
        got = [e.name for e in plugins._eligible("maverick.tools", "tool")]
        assert got == ["a"]
