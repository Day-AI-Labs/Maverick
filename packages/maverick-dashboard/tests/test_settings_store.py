"""Cross-process/in-process locking contract for the dashboard settings
overlay mutators. set_channel/clear_channel do a read-modify-write of the
single dashboard-config.toml file and MUST hold _locked() across it, exactly
like set_provider/clear_provider/set_toggle -- otherwise two concurrent saves
read the same base snapshot and the second _write() clobbers the first,
silently dropping a freshly saved credential (lost update)."""
from __future__ import annotations

import threading

import pytest


def _lock_held_during(monkeypatch, call) -> bool:
    """Run ``call`` with load_overlay() instrumented to report whether the
    in-process settings lock is held while the mutator is reading the overlay.
    _locked() acquires the (non-reentrant) _SETTINGS_LOCK, so a non-blocking
    acquire from inside load_overlay() fails iff the mutator holds the lock."""
    from maverick_dashboard import settings_store

    held: list[bool] = []
    real_load = settings_store.load_overlay

    def probing_load():
        acquired = settings_store._SETTINGS_LOCK.acquire(blocking=False)
        if acquired:
            settings_store._SETTINGS_LOCK.release()
        held.append(not acquired)  # not acquirable -> mutator already holds it
        return real_load()

    monkeypatch.setattr(settings_store, "load_overlay", probing_load)
    call(settings_store)
    return bool(held) and all(held)


def test_set_channel_holds_lock(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    held = _lock_held_during(
        monkeypatch,
        lambda s: s.set_channel("telegram", True, {"bot_token": "tok-12345"}),  # pragma: allowlist secret
    )
    assert held, "set_channel must hold _locked() during its read-modify-write"


def test_clear_channel_holds_lock(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick_dashboard import settings_store

    settings_store.set_channel("telegram", True, {"bot_token": "tok-12345"})  # pragma: allowlist secret
    held = _lock_held_during(monkeypatch, lambda s: s.clear_channel("telegram"))
    assert held, "clear_channel must hold _locked() during its read-modify-write"


def test_concurrent_channel_and_provider_both_apply(monkeypatch, tmp_path):
    """A set_channel racing a set_provider (different sections of one overlay
    file) must not have either change clobbered by a stale re-read."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick import config
    for v in config.PROVIDER_KEY_ENV_VARS + config.PROVIDER_BASE_URL_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    from maverick_dashboard import settings_store

    barrier = threading.Barrier(2)

    def do_channel():
        barrier.wait()
        settings_store.set_channel("telegram", True, {"bot_token": "tok-channel"})  # pragma: allowlist secret

    def do_provider():
        barrier.wait()
        settings_store.set_provider("anthropic", api_key="sk-test-prov")  # pragma: allowlist secret

    ts = [threading.Thread(target=do_channel), threading.Thread(target=do_provider)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    overlay = settings_store.load_overlay()
    assert overlay.get("channels", {}).get("telegram", {}).get("bot_token") == "tok-channel"  # pragma: allowlist secret
    assert overlay.get("providers", {}).get("anthropic", {}).get("api_key") == "sk-test-prov"  # pragma: allowlist secret


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
