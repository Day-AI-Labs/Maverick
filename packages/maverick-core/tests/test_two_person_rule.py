"""two_person_rule: dual-control sign-off validation."""
from __future__ import annotations

from maverick.tools.two_person_rule import two_person_rule


def _check(**kw):
    return two_person_rule().fn({"op": "check", **kw})


def test_satisfied_two_distinct_approvers():
    out = _check(signoffs=[{"approver": "alice"}, {"approver": "bob"}])
    assert out.startswith("SATISFIED") and "2 distinct approver" in out


def test_blocked_single_approver():
    out = _check(signoffs=[{"approver": "alice"}])
    assert out.startswith("BLOCKED") and "need 2" in out


def test_duplicate_approver_counts_once():
    out = _check(signoffs=[{"approver": "alice"}, {"approver": "Alice"}])
    assert out.startswith("BLOCKED")  # same person twice != two-person


def test_requester_excluded_separation_of_duties():
    out = _check(requester="alice",
                 signoffs=[{"approver": "alice"}, {"approver": "bob"}])
    assert out.startswith("BLOCKED")
    assert "separation of duties" in out


def test_distinct_roles_required():
    same_role = _check(require_distinct_roles=True,
                       signoffs=[{"approver": "a", "role": "ops"}, {"approver": "b", "role": "ops"}])
    assert same_role.startswith("BLOCKED") and "distinct role" in same_role
    diff_role = _check(require_distinct_roles=True,
                       signoffs=[{"approver": "a", "role": "ops"}, {"approver": "b", "role": "security"}])
    assert diff_role.startswith("SATISFIED")


def test_custom_min_approvers():
    out = _check(min_approvers=3,
                 signoffs=[{"approver": "a"}, {"approver": "b"}])
    assert out.startswith("BLOCKED") and "need 3" in out


def test_errors():
    t = two_person_rule()
    assert t.fn({"op": "check"}).startswith("ERROR")  # no signoffs
    assert t.fn({"op": "nope", "signoffs": []}).startswith("ERROR")


def test_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        workdir = "."

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    assert "two_person_rule" in names
