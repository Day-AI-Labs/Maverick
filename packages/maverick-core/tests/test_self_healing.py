"""Self-healing UX: failure classification + concrete remedies."""
from __future__ import annotations

from maverick.self_healing import diagnose, heal_report, remedies
from maverick.world_model import WorldModel


def test_diagnose_classes():
    assert diagnose("BudgetExceeded: $5.20 > $5.00") == "budget_exceeded"
    assert diagnose("provider returned 401 invalid api key") == "provider_auth"
    assert diagnose("429 rate limit hit") == "rate_limited"
    assert diagnose("⚠ BLOCKED by Shield (high)") == "shield_blocked"
    assert diagnose("Docker not available. Install Docker") == "sandbox_missing"
    assert diagnose("command timed out after 60s") == "timeout"
    assert diagnose("halted by killswitch") == "killswitch"
    assert diagnose("some novel explosion") == "unknown"


def test_remedies_have_commands():
    for cls in ("budget_exceeded", "provider_auth", "rate_limited",
                "shield_blocked", "sandbox_missing", "timeout",
                "killswitch", "unknown"):
        rs = remedies(cls)
        assert rs, cls
        assert all(r.command for r in rs)


def test_budget_remedies_mention_self_tuning():
    assert any("self_tuning" in r.command for r in remedies("budget_exceeded"))


def test_heal_report_for_failed_goal(tmp_path):
    w = WorldModel(tmp_path / "world.db")
    gid = w.create_goal("g", "")
    w.set_goal_status(gid, "failed", result="BudgetExceeded: $9 > $5")
    out = heal_report(w, gid)
    assert "diagnosis: budget_exceeded" in out
    assert "nothing auto-applied" in out
    assert "--max-dollars" in out
    w.close()


def test_heal_report_non_failed_goal(tmp_path):
    w = WorldModel(tmp_path / "world.db")
    gid = w.create_goal("g", "")
    w.set_goal_status(gid, "done")
    assert "nothing to heal" in heal_report(w, gid)
    assert "not found" in heal_report(w, 999)
    w.close()
