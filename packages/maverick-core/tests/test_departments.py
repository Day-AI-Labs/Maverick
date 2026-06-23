"""Department bundles: the specialist packs grouped into deployable teams."""
from __future__ import annotations

from maverick import departments as dept
from maverick.domain import SUITE_PREFIXES, suite_for


def test_finance_is_a_department_with_finance_packs():
    d = dept.get_department("finance")
    assert d is not None
    assert d.title == "Finance"
    assert d.charter  # authored charter, non-empty
    assert d.headcount > 0
    # Every member resolves back to the finance suite.
    assert all(suite_for(name) == "finance" for name in d.members)
    # Roster is sorted and deduplicated.
    assert d.members == sorted(set(d.members))


def test_list_departments_covers_only_real_suites_sorted_by_title():
    depts = dept.list_departments()
    assert depts, "expected at least one populated department"
    titles = [d.title for d in depts]
    assert titles == sorted(titles)
    valid_suites = set(SUITE_PREFIXES.values())
    assert all(d.key in valid_suites for d in depts)
    # No empty departments are listed.
    assert all(d.headcount > 0 for d in depts)


def test_roster_returns_domain_profiles_for_the_team():
    profiles = dept.roster("finance")
    assert profiles
    names = {p.name for p in profiles}
    assert names == set(dept.get_department("finance").members)


def test_disabled_suite_drops_the_department():
    cfg = {"suites": {"finance": False}}
    keys = {d.key for d in dept.list_departments(cfg)}
    assert "finance" not in keys
    assert dept.get_department("finance", cfg) is None
    assert dept.roster("finance", cfg) == []


def test_unknown_suite_key_is_none():
    assert dept.get_department("not_a_suite") is None


def test_title_and_charter_fallback_for_unlabeled_suite():
    # A suite key with no SUITE_LABELS entry still gets a derived title.
    assert dept.department_title("some_new_suite") == "Some New Suite"
    assert dept.department_charter("some_new_suite") == ""
