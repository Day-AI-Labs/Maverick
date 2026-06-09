"""geofence: region allow/deny policy checks."""
from __future__ import annotations

from maverick.tools.geofence import geofence


def _check(region, policy):
    return geofence().fn({"op": "check", "region": region, "policy": policy})


def test_deny_wins_over_allow():
    out = _check("CN", {"allow": ["CN"], "deny": ["CN"]})
    assert out.startswith("DENY CN") and "deny-list" in out


def test_allow_list_membership():
    assert _check("DE", {"allow": ["DE", "FR"]}).startswith("ALLOW DE")
    assert _check("US", {"allow": ["DE", "FR"]}).startswith("DENY US")


def test_named_group_expansion():
    # DE is in EU; an EU allow-list permits it
    assert _check("DE", {"allow": ["EU"]}).startswith("ALLOW DE")
    # NO is EEA but not EU
    assert _check("NO", {"allow": ["EU"]}).startswith("DENY NO")
    assert _check("NO", {"allow": ["EEA"]}).startswith("ALLOW NO")
    # group in deny-list
    assert _check("FR", {"deny": ["EU"]}).startswith("DENY FR")


def test_default_when_no_allow_list():
    assert _check("BR", {"deny": ["CN"], "default": "allow"}).startswith("ALLOW BR")
    assert _check("BR", {"deny": ["CN"], "default": "deny"}).startswith("DENY BR")
    # default defaults to deny
    assert _check("BR", {}).startswith("DENY BR")


def test_case_insensitive():
    assert _check("de", {"allow": ["eu"]}).startswith("ALLOW DE")


def test_errors():
    t = geofence()
    assert t.fn({"op": "check", "region": "", "policy": {}}).startswith("ERROR")
    assert t.fn({"op": "check", "region": "US"}).startswith("ERROR")  # no policy
    assert t.fn({"op": "nope", "region": "US", "policy": {}}).startswith("ERROR")


def test_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        workdir = "."

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    assert "geofence" in names
