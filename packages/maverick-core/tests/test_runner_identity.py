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

    monkeypatch.setattr(world_model, "open_world", lambda *a, **k: FakeWorld())
    monkeypatch.setattr(llm_mod, "LLM", lambda: object())
    monkeypatch.setattr(sandbox_mod, "build_sandbox", lambda: object())
    monkeypatch.setattr(budget_mod, "budget_from_config", lambda **_kwargs: object())
    monkeypatch.setattr(orchestrator, "run_goal_sync", fake_run_goal_sync)

    assert runner.run_goal_in_thread(42, max_depth=2, channel="api", user_id="alice") == "done"
    assert captured["channel"] == "api"
    assert captured["user_id"] == "alice"
    assert captured["resume"] is True


def test_run_goal_in_thread_can_schedule_by_caller_principal(monkeypatch):
    """Fleet runs keep agent audit identity but share the caller's fair lane."""
    from maverick import budget as budget_mod
    from maverick import llm as llm_mod
    from maverick import orchestrator, runner, world_model
    from maverick import sandbox as sandbox_mod

    captured: dict = {}
    lanes: list[str | None] = []

    class FakeWorld:
        def get_goal(self, goal_id):
            return SimpleNamespace(id=goal_id, status="done")

        def close(self):
            pass

    class FakeSemaphore:
        def acquire(self, timeout=None):
            return True

        def release(self):
            pass

    def fake_run_goal_sync(*args, **kwargs):
        captured.update(kwargs)
        return "DONE."

    def fake_principal_semaphore(principal):
        lanes.append(principal)
        return FakeSemaphore()

    monkeypatch.setattr(runner, "_principal_semaphore", fake_principal_semaphore)
    monkeypatch.setattr(world_model, "open_world", lambda *a, **k: FakeWorld())
    monkeypatch.setattr(llm_mod, "LLM", lambda: object())
    monkeypatch.setattr(sandbox_mod, "build_sandbox", lambda: object())
    monkeypatch.setattr(budget_mod, "budget_from_config", lambda **_kwargs: object())
    monkeypatch.setattr(orchestrator, "run_goal_sync", fake_run_goal_sync)

    assert runner.run_goal_in_thread(
        42,
        max_depth=2,
        channel="fleet",
        user_id="agent:acme.coder",
        concurrency_principal="user:alice",
    ) == "done"
    assert lanes == ["user:alice"]
    assert captured["channel"] == "fleet"
    assert captured["user_id"] == "agent:acme.coder"
