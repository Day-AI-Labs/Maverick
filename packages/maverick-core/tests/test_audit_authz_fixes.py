"""Regression for autonomy-graduation principal confusion (audit finding c0).

graduation_status matched history records by SUBSTRING (``name in principal``),
so an agent whose name is a substring of other agents graduated to unsupervised
autonomy on THEIR approval history -- e.g. ``analyst`` graduating on
``agent:data_analyst-0``'s record. Now matched by exact agent identity.
"""
from maverick.agent_autonomy import graduation_status


def _approved(principal, n):
    return [{"requested_by": principal, "decision": "approved"} for _ in range(n)]


def test_graduation_does_not_borrow_a_superstring_agents_history():
    hist = _approved("agent:data_analyst-0", 12)
    v = graduation_status("analyst", hist)  # 'analyst' is a substring of 'data_analyst'
    assert v.sample == 0
    assert v.graduated is False


def test_graduation_does_not_pool_unrelated_clerks():
    hist = _approved("agent:fin_clerk-0", 6) + _approved("agent:hr_clerk-0", 6)
    v = graduation_status("clerk", hist)
    assert v.sample == 0
    assert v.graduated is False


def test_exact_identity_still_graduates():
    hist = _approved("agent:data_analyst-0", 12)
    v = graduation_status("data_analyst", hist)
    assert v.sample == 12
    assert v.graduated is True


def test_depth_suffix_and_bare_principal_match_exactly():
    assert graduation_status("fin_clerk", _approved("agent:fin_clerk-3", 10)).sample == 10
    assert graduation_status("fin_clerk", _approved("fin_clerk", 10)).sample == 10
    # a different exact agent must not pick these up
    assert graduation_status("clerk", _approved("agent:fin_clerk-3", 10)).sample == 0
