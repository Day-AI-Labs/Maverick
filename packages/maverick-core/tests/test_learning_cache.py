"""Cross-run learning cache: roundtrip + normalization equivalence, TTL via an
injected clock, the LRU cap, secret refusal, required provenance, and the
off-by-default knob. Fully offline; the secret fixture is built at runtime so
no real-looking credential is committed."""
from __future__ import annotations

import pytest
from maverick import learning_cache as lc


@pytest.fixture
def now():
    return {"t": 1_000_000.0}


@pytest.fixture
def cache(tmp_path, now):
    return lc.LearningCache(tmp_path / "lc.json", clock=lambda: now["t"])


def test_roundtrip_and_normalization_equivalence(cache):
    cache.put("Build  the APP.", "make -j test", verified_by="verifier:goal-1")
    entry = cache.get("build the app")  # different casing/spacing/punctuation
    assert entry is not None
    assert entry["result"] == "make -j test"
    assert entry["verified_by"] == "verifier:goal-1"
    assert lc.task_key("Build  the APP.") == lc.task_key("build the app")
    assert lc.normalize("Build  the APP.") == "build the app"
    assert cache.get("a different task") is None


def test_persists_across_instances_with_0600(tmp_path, now):
    path = tmp_path / "lc.json"
    first = lc.LearningCache(path, clock=lambda: now["t"])
    first.put("repo build command", "make build", verified_by="verifier:g2")
    assert (path.stat().st_mode & 0o777) == 0o600
    second = lc.LearningCache(path, clock=lambda: now["t"])  # a fresh "run"
    assert second.get("Repo build command")["result"] == "make build"


def test_temp_file_is_restrictive_before_replace(tmp_path, now, monkeypatch):
    path = tmp_path / "lc.json"
    cache = lc.LearningCache(path, clock=lambda: now["t"])
    original_replace = lc.os.replace
    observed = {}
    old_umask = lc.os.umask(0o022)

    def assert_tmp_mode_before_replace(src, dst):
        observed["mode"] = src.stat().st_mode & 0o777
        observed["contains_result"] = "private ops data" in src.read_text(encoding="utf-8")
        return original_replace(src, dst)

    try:
        monkeypatch.setattr(lc.os, "replace", assert_tmp_mode_before_replace)
        cache.put("private task", "private ops data", verified_by="verifier:g2")
    finally:
        lc.os.umask(old_umask)

    assert observed == {"mode": 0o600, "contains_result": True}
    assert (path.stat().st_mode & 0o777) == 0o600


def test_ttl_expiry_with_injected_clock(cache, now):
    cache.put("schema for svc Y", "{...}", verified_by="verifier:g3", ttl_days=1)
    assert cache.get("schema for svc Y") is not None
    now["t"] += 86_400.0 + 1  # one day + 1s later
    assert cache.get("schema for svc Y") is None
    assert cache.stats()["entries"] == 0  # expired entry was dropped, not kept


def test_lru_cap_evicts_least_recently_used(tmp_path, now):
    cache = lc.LearningCache(tmp_path / "lc.json", max_entries=2, clock=lambda: now["t"])
    cache.put("task a", "ra", verified_by="v:1")
    now["t"] += 1
    cache.put("task b", "rb", verified_by="v:1")
    now["t"] += 1
    cache.get("task a")  # bump a's recency above b's
    now["t"] += 1
    cache.put("task c", "rc", verified_by="v:1")  # over cap -> evict b
    assert cache.get("task b") is None
    assert cache.get("task a") is not None
    assert cache.get("task c") is not None


def test_refuses_to_store_secrets(cache):
    # Constructed at runtime: obviously fake, but matches the anthropic key
    # pattern the detector knows.
    fake_secret = "sk-ant-" + "a" * 24
    with pytest.raises(ValueError, match="secret"):
        cache.put("api key for x", f"the key is {fake_secret}", verified_by="v:1")
    assert cache.get("api key for x") is None
    assert cache.stats()["entries"] == 0


def test_verified_by_is_required(cache):
    with pytest.raises(TypeError):
        cache.put("task", "result")  # no verified_by at all
    with pytest.raises(ValueError, match="verified_by"):
        cache.put("task", "result", verified_by="   ")
    with pytest.raises(ValueError):
        cache.put("task", "result", verified_by="v:1", ttl_days=0)


def test_invalidate_prune_stats_and_tags(cache, now):
    cache.put("short lived", "x", verified_by="v:1", ttl_days=1, tags=["build"])
    cache.put("long lived", "y", verified_by="v:1", ttl_days=10)
    assert cache.get("short lived")["tags"] == ["build"]
    now["t"] += 2 * 86_400.0
    assert cache.prune() == 1  # only the expired entry goes
    assert cache.stats()["entries"] == 1
    assert cache.invalidate("long lived") is True
    assert cache.invalidate("long lived") is False
    assert cache.stats()["entries"] == 0


def test_corrupt_file_fails_open(tmp_path, now):
    path = tmp_path / "lc.json"
    path.write_text("{not json", encoding="utf-8")
    cache = lc.LearningCache(path, clock=lambda: now["t"])
    assert cache.stats()["entries"] == 0
    cache.put("t", "r", verified_by="v:1")  # and it still works
    assert cache.get("t")["result"] == "r"


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("MAVERICK_LEARNING_CACHE", raising=False)
    import maverick.config as config_mod
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: {})
    assert lc.enabled() is False
    monkeypatch.setenv("MAVERICK_LEARNING_CACHE", "1")
    assert lc.enabled() is True
    monkeypatch.delenv("MAVERICK_LEARNING_CACHE", raising=False)
    monkeypatch.setattr(
        config_mod, "load_config", lambda *a, **k: {"memory": {"learning_cache": True}},
    )
    assert lc.enabled() is True


def test_shared_singleton_and_reset():
    lc.reset_shared()
    try:
        a = lc.shared()
        assert a is lc.shared()
        lc.reset_shared()
        assert lc.shared() is not a
    finally:
        lc.reset_shared()
