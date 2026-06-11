"""Secrets posted to the blackboard must not PERSIST/DISPLAY in cleartext.

Security finding (round 7, adversarial): Blackboard.post() mirrored content
verbatim into world.goal_events (persisted to world.db and streamed live to
the dashboard), the replay trace, and the observation channel -- none
redacted. An agent that reports a credential it found ("the DB password is X")
leaked that secret to disk and to any dashboard viewer, even in a fully local
deployment, and regardless of the audit log's own redaction.

The in-memory blackboard (the agents' shared working memory) stays verbatim so
agent workflows that legitimately pass a value between siblings are unbroken --
same split the audit log uses (the live agent operates on real data; the
persisted/displayed record is redacted).
"""
from __future__ import annotations

from maverick.blackboard import Blackboard
from maverick.world_model import WorldModel

_SECRET = "sk-ant-api03-LEAKED1234567890abcdefABCDEFGHIJKLMNOP"  # pragma: allowlist secret


def test_secret_not_persisted_to_goal_events(tmp_path):
    world = WorldModel(tmp_path / "world.db")
    gid = world.create_goal("t", "")
    bb = Blackboard()
    bb.attach_world(world, gid)

    bb.post("worker-1", "finding", f"Found the API key: {_SECRET} in config")

    events = world.goal_events(gid)
    assert events, "post should mirror to goal_events"
    blob = "\n".join(e.content for e in events)
    assert _SECRET not in blob, "secret leaked into persisted/displayed goal_events"
    assert "[REDACTED" in blob


def test_in_memory_blackboard_preserves_content_for_agents(tmp_path):
    # The agents' shared working memory is intentionally verbatim so a value
    # passed between siblings still works; only the persisted mirror redacts.
    world = WorldModel(tmp_path / "world.db")
    gid = world.create_goal("t", "")
    bb = Blackboard()
    bb.attach_world(world, gid)
    bb.post("worker-1", "finding", f"value={_SECRET}")
    assert _SECRET in bb.render(10)


def test_no_world_still_works(tmp_path):
    # Detached blackboard (no world) must not crash on a secret post.
    bb = Blackboard()
    bb.post("a", "finding", f"key {_SECRET}")
    assert _SECRET in bb.render(10)
