from __future__ import annotations

import asyncio
from dataclasses import dataclass


class _World:
    def __init__(self):
        self.conversation_key = None
        self.turns = []
        self.goals = []

    def get_or_create_conversation(self, channel, user_id):
        self.conversation_key = (channel, user_id)
        return type("Conversation", (), {"id": 1})()

    def append_turn(self, conversation_id, role, text):
        self.turns.append((conversation_id, role, text))

    def create_goal(self, title, text):
        self.goals.append((title, text))
        return 7

    def set_goal_status(self, *args, **kwargs):
        return None


@dataclass(frozen=True)
class _Principal:
    principal: str


def _server(server_mod):
    srv = server_mod.Server.__new__(server_mod.Server)
    srv.world = _World()
    srv.llm = object()
    srv.sandbox = object()
    srv.max_depth = 3
    srv._channels = []
    srv._tasks = []
    srv._shield = None
    return srv


def test_oidc_enabled_rejects_message_without_token(monkeypatch):
    from maverick import oidc as oidc_mod
    from maverick import server as server_mod

    monkeypatch.setattr(oidc_mod, "oidc_enabled", lambda: True)
    seen_tokens = []

    def _reject(token):
        seen_tokens.append(token)
        raise oidc_mod.OIDCError("missing token")

    async def _run_goal_must_not_run(*args, **kwargs):
        raise AssertionError("run_goal must not run without a verified OIDC token")

    monkeypatch.setattr(oidc_mod, "verify_oidc_token", _reject)
    monkeypatch.setattr(server_mod, "run_goal", _run_goal_must_not_run)

    class _Msg:
        channel = "slack"
        user_id = "CROOM"
        principal_id = "attacker"
        text = "spend budget"

    srv = _server(server_mod)
    out = asyncio.run(srv._handle_message(_Msg()))

    assert "Authentication failed" in out
    assert seen_tokens == [""]
    assert srv.world.goals == []
    assert srv.world.turns == []


def test_oidc_enabled_uses_verified_principal_for_goal_context(monkeypatch):
    from maverick import oidc as oidc_mod
    from maverick import server as server_mod

    monkeypatch.setattr(oidc_mod, "oidc_enabled", lambda: True)
    monkeypatch.setattr("maverick.paths.tenant_by_user_enabled", lambda: False)
    monkeypatch.setattr(
        "maverick.compliance.first_turn_disclosure", lambda *a, **k: None
    )

    seen_tokens = []

    def _verify(token):
        seen_tokens.append(token)
        return _Principal("user:alice")

    captured = {}

    async def _fake_run_goal(*args, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(oidc_mod, "verify_oidc_token", _verify)
    monkeypatch.setattr(server_mod, "run_goal", _fake_run_goal)
    monkeypatch.setattr(server_mod, "budget_from_config", lambda: object())

    class _Msg:
        channel = "slack"
        user_id = "CROOM"  # reply target, not trusted as the authenticated user
        principal_id = "attacker"
        authorization = "Bearer signed.jwt"
        text = "hello"

    srv = _server(server_mod)
    out = asyncio.run(srv._handle_message(_Msg()))

    assert out == "ok"
    assert seen_tokens == ["signed.jwt"]
    assert srv.world.conversation_key == ("slack", "user:alice")
    assert srv.world.turns == [(1, "user", "hello")]
    assert srv.world.goals == [("hello", "hello")]
    assert captured["channel"] == "slack"
    assert captured["user_id"] == "slack:user:alice"
