"""semver_check: version-constraint satisfaction."""
from __future__ import annotations

from maverick.tools.semver_check import semver_check


def _c(version, constraint):
    return semver_check().fn({"op": "check", "version": version, "constraint": constraint})


def test_comparator_range_satisfied():
    out = _c("1.5.0", ">=1.2.0,<2.0.0")
    assert out.startswith("SATISFIED")


def test_comparator_range_unsatisfied():
    out = _c("2.0.0", ">=1.2.0,<2.0.0")
    assert out.startswith("UNSATISFIED")
    assert "fails <2.0.0" in out


def test_caret_major():
    assert _c("1.9.9", "^1.2.3").startswith("SATISFIED")
    assert _c("2.0.0", "^1.2.3").startswith("UNSATISFIED")
    assert _c("1.2.2", "^1.2.3").startswith("UNSATISFIED")


def test_caret_zero_minor():
    # ^0.2.3 -> >=0.2.3 <0.3.0
    assert _c("0.2.5", "^0.2.3").startswith("SATISFIED")
    assert _c("0.3.0", "^0.2.3").startswith("UNSATISFIED")


def test_tilde():
    # ~1.2.3 -> >=1.2.3 <1.3.0
    assert _c("1.2.9", "~1.2.3").startswith("SATISFIED")
    assert _c("1.3.0", "~1.2.3").startswith("UNSATISFIED")


def test_exact_and_star():
    assert _c("1.2.3", "1.2.3").startswith("SATISFIED")
    assert _c("1.2.4", "=1.2.3").startswith("UNSATISFIED")
    assert _c("9.9.9", "*").startswith("SATISFIED")


def test_prerelease_ordering():
    # prerelease is lower than the release
    assert _c("1.0.0-rc.1", "<1.0.0").startswith("SATISFIED")
    assert _c("1.0.0", ">1.0.0-rc.1").startswith("SATISFIED")


def test_partial_version_padding():
    # constraint and version may omit trailing components
    assert _c("1.2", ">=1.0").startswith("SATISFIED")


def test_errors():
    t = semver_check()
    assert t.fn({"op": "check", "version": "", "constraint": "*"}).startswith("ERROR")
    assert t.fn({"op": "check", "version": "notsemver", "constraint": "*"}).startswith("ERROR")
    assert t.fn({"op": "check", "version": "1.0.0", "constraint": ">=bad"}).startswith("ERROR")
    assert t.fn({"op": "nope", "version": "1.0.0", "constraint": "*"}).startswith("ERROR")


def test_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        workdir = "."

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    assert "semver_check" in names
