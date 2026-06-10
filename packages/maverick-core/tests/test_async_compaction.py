"""Async compaction: precomputed-prefix cache semantics, scheduling, and the
off-by-default knob. The executor is injected so everything runs synchronously."""
from __future__ import annotations

from maverick import async_compaction as ac
from maverick import context_compactor as _cc


def _msgs(n, prefix="m"):
    return [{"role": "user", "content": f"{prefix}{i} " + "word " * 30} for i in range(n)]


def _sync_compactor():
    return ac.BackgroundCompactor(executor=lambda fn: fn())


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("MAVERICK_ASYNC_COMPACTION", raising=False)
    import maverick.config as config_mod
    monkeypatch.setattr(config_mod, "load_config", lambda: {})
    assert ac.enabled() is False
    monkeypatch.setenv("MAVERICK_ASYNC_COMPACTION", "1")
    assert ac.enabled() is True


def test_cold_start_compacts_inline_and_schedules():
    bc = _sync_compactor()
    messages = _msgs(10)
    out = bc.compact_with_precompute("conv:1", messages, target_tokens=100)
    # Same result as inline compaction (cold start path).
    assert out  # produced something at budget
    # The prefix (len-4) was precomputed by the injected executor.
    assert bc.stats()["cached_keys"] == 1


def test_warm_hit_uses_precomputed_prefix(monkeypatch):
    bc = _sync_compactor()
    messages = _msgs(10)
    bc.compact_with_precompute("conv:2", messages, target_tokens=100)  # warm the cache

    calls = []
    real = _cc.compact

    def spy(msgs, target_tokens):
        calls.append(len(msgs))
        return real(msgs, target_tokens=target_tokens)

    monkeypatch.setattr(ac._cc, "compact", spy)
    bc.compact_with_precompute("conv:2", messages, target_tokens=100)
    # Hot path compacted (precomputed_prefix + 4 tail) -- strictly fewer
    # messages than the full window -- plus the background refresh of the
    # 6-message prefix. Never the full 10 inline.
    hot_call = calls[0]
    assert hot_call < 10, f"hot path got {hot_call} messages, expected < window"


def test_prefix_change_invalidates():
    bc = _sync_compactor()
    a = _msgs(10, "a")
    bc.compact_with_precompute("conv:3", a, target_tokens=100)
    b = _msgs(10, "b")  # different content, same length
    out = bc.compact_with_precompute("conv:3", b, target_tokens=100)
    assert out  # no stale mixing; fingerprint mismatch -> inline path
    # Cache refreshed for the new prefix.
    assert bc.stats()["cached_keys"] == 1


def test_short_history_no_prefix():
    bc = _sync_compactor()
    out = bc.compact_with_precompute("conv:4", _msgs(2), target_tokens=100)
    assert len(out) == 2  # nothing to precompute; passthrough compaction
    assert bc.stats()["cached_keys"] == 0


def test_keys_are_independent():
    bc = _sync_compactor()
    bc.compact_with_precompute("conv:a", _msgs(8, "x"), target_tokens=100)
    bc.compact_with_precompute("conv:b", _msgs(8, "y"), target_tokens=100)
    assert bc.stats()["cached_keys"] == 2


def test_compactor_error_does_not_raise():
    def boom(fn):
        fn()

    bc = ac.BackgroundCompactor(executor=boom)
    # Force the background compute to fail; the hot path must be unaffected.
    import maverick.async_compaction as mod
    real = mod._cc.compact
    try:
        calls = {"n": 0}

        def flaky(msgs, target_tokens):
            calls["n"] += 1
            if calls["n"] > 1:  # first (inline) OK, background fails
                raise RuntimeError("background boom")
            return real(msgs, target_tokens=target_tokens)

        mod._cc.compact = flaky
        out = bc.compact_with_precompute("conv:e", _msgs(10), target_tokens=100)
        assert out
        assert bc.stats()["cached_keys"] == 0  # failed compute cached nothing
    finally:
        mod._cc.compact = real
