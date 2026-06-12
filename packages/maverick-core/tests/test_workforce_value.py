"""Workforce value report: throughput + economics + compounding + governance."""
from __future__ import annotations

from types import SimpleNamespace

from maverick import workforce_value


class _World:
    def __init__(self, episodes, goal_domains):
        self._eps = episodes
        self._domains = goal_domains

    def list_episodes(self, limit=5000, goal_id=None):
        return self._eps[:limit]

    def get_goal(self, goal_id):
        dom = self._domains.get(goal_id)
        return SimpleNamespace(domain=dom) if dom is not None else None


def _ep(goal_id, *, cost, outcome, started_at=1000.0):
    return SimpleNamespace(id=goal_id, goal_id=goal_id, started_at=started_at,
                           ended_at=started_at + 1, outcome=outcome,
                           cost_dollars=cost, input_tokens=0, output_tokens=0,
                           tool_calls=0)


class TestEconomics:
    def test_cost_avoided_and_roi(self):
        world = _World(
            episodes=[
                _ep(1, cost=2.0, outcome="success"),
                _ep(2, cost=3.0, outcome="success"),
                _ep(3, cost=1.0, outcome="failure"),  # cost counts, no deliverable
            ],
            goal_domains={1: "finance_sox", 2: "finance_sox", 3: "legal_x"},
        )
        v = workforce_value.compute(world, window_days=365, human_cost=50.0,
                                    now=2000.0)
        assert v.deliverables == 2
        assert v.agent_cost == 6.0           # 2+3+1
        assert v.human_baseline == 100.0     # 2 deliverables * 50
        assert v.cost_avoided == 94.0
        assert round(v.roi_multiple, 2) == round(100.0 / 6.0, 2)

    def test_window_excludes_old_episodes(self):
        world = _World(
            episodes=[
                _ep(1, cost=1.0, outcome="success", started_at=100.0),   # old
                _ep(2, cost=1.0, outcome="success", started_at=1_000_000.0),
            ],
            goal_domains={1: "x", 2: "x"},
        )
        v = workforce_value.compute(world, window_days=1, now=1_000_050.0)
        assert v.deliverables == 1

    def test_department_breakdown_sorted_by_avoided(self):
        world = _World(
            episodes=[
                _ep(1, cost=1.0, outcome="success"),
                _ep(2, cost=1.0, outcome="success"),
                _ep(3, cost=1.0, outcome="success"),
            ],
            goal_domains={1: "finance_sox", 2: "finance_sox", 3: "gtm_x"},
        )
        v = workforce_value.compute(world, window_days=365, human_cost=50.0,
                                    now=2000.0)
        assert v.by_department[0].department == "finance_sox"
        assert v.by_department[0].deliverables == 2

    def test_unattributed_when_no_domain(self):
        world = _World([_ep(1, cost=1.0, outcome="success")], goal_domains={})
        v = workforce_value.compute(world, window_days=365, now=2000.0)
        assert v.by_department[0].department == "(unattributed)"


class TestCompounding:
    def test_improvement_from_hindsight_ledger(self, tmp_path, monkeypatch):
        import maverick.dreaming as dreaming
        ledger = tmp_path / "hindsight.ndjson"
        ledger.write_text(
            '{"ts": 1000.0, "covered_now": 3}\n'
            '{"ts": 2000.0, "covered_now": 5}\n'
            '{"ts": 3000.0, "covered_now": 8}\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(dreaming, "_tenant_path", lambda name, legacy: ledger)
        world = _World([], {})
        v = workforce_value.compute(world, window_days=365, now=3001.0 + 0)
        # now must be close enough that 1000.0 is within the window:
        v = workforce_value.compute(world, window_days=100000, now=3001.0)
        assert len(v.coverage_trend) == 3
        assert v.improvement == 5  # 8 - 3

    def test_improvement_none_without_history(self):
        v = workforce_value.compute(_World([], {}), window_days=90)
        assert v.improvement is None


class TestRender:
    def test_report_is_executive_readable(self):
        world = _World([_ep(1, cost=2.0, outcome="success")],
                       {1: "finance_sox"})
        v = workforce_value.compute(world, window_days=365, human_cost=50.0,
                                    now=2000.0)
        text = workforce_value.format_report(v)
        assert "AI Workforce" in text
        assert "Cost avoided" in text
        assert "finance_sox" in text

    def test_to_dict_roundtrips_key_numbers(self):
        world = _World([_ep(1, cost=2.0, outcome="success")], {1: "x"})
        v = workforce_value.compute(world, window_days=365, human_cost=50.0,
                                    now=2000.0)
        d = workforce_value.to_dict(v)
        assert d["deliverables"] == 1
        assert d["cost_avoided"] == 48.0
        assert d["by_department"][0]["department"] == "x"
