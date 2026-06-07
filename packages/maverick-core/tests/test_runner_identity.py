from __future__ import annotations

from types import SimpleNamespace


def test_run_goal_in_thread_propagates_execution_identity(monkeypatch):
    """HTTP adapters can pass an authenticated user through the runner."""
    from maverick import budget as budget_mod
    from maverick import llm as llm_mod
    from maverick import orchestrator, runner, world_model
    from maverick import sandbox as sandbox_mod

    captured: dict = {}

    class FakeWorld:
        def get_goal(self, goal_id):
            return SimpleNamespace(id=goal_id, status="done")

        def close(self):
            pass

    def fake_run_goal_sync(*args, **kwargs):
        captured.update(kwargs)
        return "DONE."

    monkeypatch.setattr(world_model, "open_world", lambda _db: FakeWorld())
    monkeypatch.setattr(llm_mod, "LLM", lambda: object())
    monkeypatch.setattr(sandbox_mod, "build_sandbox", lambda: object())
    monkeypatch.setattr(budget_mod, "budget_from_config", lambda **_kwargs: object())
    monkeypatch.setattr(orchestrator, "run_goal_sync", fake_run_goal_sync)

    assert runner.run_goal_in_thread(42, max_depth=2, channel="api", user_id="alice") == "done"
    assert captured["channel"] == "api"
    assert captured["user_id"] == "alice"
    assert captured["resume"] is True
