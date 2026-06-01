"""Q3 2026 batch 2: Podman sandbox, GitLab tool, embeddings tool,
provider health board, cost-aware router."""
from __future__ import annotations

import sys
import time
import types
from unittest.mock import MagicMock

# ---------- Podman sandbox ----------

def test_podman_verify_missing(tmp_path, monkeypatch):
    """No podman binary on PATH -> RuntimeError with actionable msg."""
    from maverick.sandbox.podman import PodmanBackend

    def _no_podman(args, *a, **k):
        if args and args[0] == "podman":
            raise FileNotFoundError("podman")
        raise AssertionError(f"unexpected: {args}")

    monkeypatch.setattr("subprocess.run", _no_podman)
    try:
        PodmanBackend(workdir=tmp_path)
    except RuntimeError as e:
        assert "podman" in str(e).lower()
        return
    raise AssertionError("expected RuntimeError")


def test_podman_exec_runs_container(tmp_path, monkeypatch):
    from maverick.sandbox.podman import PodmanBackend

    calls = {"n": 0, "args": []}

    def _fake_run(args, *a, **k):
        calls["n"] += 1
        calls["args"].append(args)
        if args[:2] == ["podman", "version"]:
            return MagicMock(returncode=0, stdout=b"", stderr=b"")
        # Match the second `podman run` call.
        return MagicMock(returncode=0, stdout="hello\n", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    backend = PodmanBackend(workdir=tmp_path, image="alpine")
    result = backend.exec("echo hello")
    assert result.exit_code == 0
    assert "hello" in result.stdout

    run_args = calls["args"][1]
    assert run_args[0] == "podman"
    assert "--rm" in run_args
    assert "--network" in run_args  # default allow_network=False
    assert "alpine" in run_args


def test_podman_allows_network_when_flag_set(tmp_path, monkeypatch):
    from maverick.sandbox.podman import PodmanBackend

    captured = {"args": None}

    def _fake_run(args, *a, **k):
        if args[:2] == ["podman", "version"]:
            return MagicMock(returncode=0, stdout=b"", stderr=b"")
        captured["args"] = args
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    backend = PodmanBackend(workdir=tmp_path, allow_network=True)
    backend.exec("true")
    assert "--network" not in captured["args"]


def test_build_sandbox_constructs_podman(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "subprocess.run",
        lambda args, *a, **k: MagicMock(returncode=0, stdout=b"", stderr=b""),
    )
    # Monkeypatch config so backend = "podman" without writing a real file.
    import maverick.config as cfg
    from maverick.sandbox import build_sandbox

    def _fake_cfg():
        return {"sandbox": {"backend": "podman", "workdir": str(tmp_path),
                            "timeout": 30}}

    monkeypatch.setattr(cfg, "load_config", _fake_cfg)
    monkeypatch.setattr(cfg, "get_sandbox", lambda: _fake_cfg()["sandbox"])
    sb = build_sandbox()
    assert sb.__class__.__name__ == "PodmanBackend"


# ---------- GitLab tool ----------

def test_gitlab_requires_op():
    from maverick.tools.gitlab import gitlab
    assert "op is required" in gitlab().fn({})


def test_gitlab_unknown_op():
    from maverick.tools.gitlab import gitlab
    out = gitlab().fn({"op": "wat"})
    assert "unknown op" in out or "ERROR" in out


def test_gitlab_missing_token(monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    fake = types.ModuleType("httpx")
    fake.Client = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake)
    from maverick.tools.gitlab import gitlab
    out = gitlab().fn({"op": "issues", "project": "group/repo"})
    assert "GITLAB_TOKEN" in out


def test_gitlab_issues_list_calls_rest(monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "glpat_xxx")
    resp = MagicMock()
    resp.json = MagicMock(return_value=[
        {"iid": 1, "state": "opened", "title": "Crash on save"},
        {"iid": 2, "state": "opened", "title": "Improve docs"},
    ])
    resp.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.get = MagicMock(return_value=resp)
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = MagicMock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    from maverick.tools.gitlab import gitlab
    out = gitlab().fn({"op": "issues", "project": "group/repo"})
    assert "Crash on save" in out and "Improve docs" in out
    assert "opened" in out
    # Verify URL-encoded project path was used.
    called_url = fake_client.get.call_args.args[0]
    assert "group%2Frepo" in called_url


def test_gitlab_issues_follows_next_page_header(monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "glpat_xxx")

    def _page(items, next_page):
        resp = MagicMock()
        resp.json = MagicMock(return_value=items)
        resp.raise_for_status = MagicMock()
        resp.headers = {"X-Next-Page": next_page}
        return resp

    fake_client = MagicMock()
    fake_client.get = MagicMock(side_effect=[
        _page([{"iid": 1, "state": "opened", "title": "Page one issue"}], "2"),
        _page([{"iid": 2, "state": "opened", "title": "Page two issue"}], ""),
    ])
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = MagicMock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    from maverick.tools.gitlab import gitlab
    out = gitlab().fn({"op": "issues", "project": "g/r", "limit": 50})
    assert "Page one issue" in out and "Page two issue" in out
    assert fake_client.get.call_count == 2
    assert fake_client.get.call_args_list[1].kwargs["params"]["page"] == 2


def test_gitlab_issue_get_404(monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "glpat_xxx")
    resp = MagicMock()
    resp.status_code = 404

    fake_client = MagicMock()
    fake_client.get = MagicMock(return_value=resp)
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = MagicMock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    from maverick.tools.gitlab import gitlab
    out = gitlab().fn({"op": "issue_get", "project": "g/r", "iid": 999})
    assert "not found" in out


def test_gitlab_pipeline_get_renders(monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "glpat_xxx")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={
        "id": 42, "status": "success", "ref": "main",
        "sha": "abc123def456", "created_at": "2026-05-27T10:00:00Z",
        "finished_at": "2026-05-27T10:05:00Z",
        "web_url": "https://gitlab.com/g/r/-/pipelines/42",
    })
    resp.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.get = MagicMock(return_value=resp)
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = MagicMock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    from maverick.tools.gitlab import gitlab
    out = gitlab().fn({"op": "pipeline_get", "project": "g/r", "pipeline_id": 42})
    assert "success" in out and "main" in out
    assert "abc123def456"[:12] in out


# ---------- embeddings tool ----------

def test_embeddings_requires_op():
    from maverick.tools.embeddings import embeddings
    assert "op is required" in embeddings().fn({})


def test_embeddings_missing_fastembed(monkeypatch):
    # Force ImportError even if fastembed is somehow installed.
    monkeypatch.setitem(sys.modules, "fastembed", None)
    from maverick.tools.embeddings import embeddings
    out = embeddings().fn({"op": "embed", "text": "hello"})
    assert "fastembed not installed" in out


def test_embeddings_embed_uses_fastembed(monkeypatch):
    """With a stub fastembed, embed returns dim + head."""
    fake_emb = types.ModuleType("fastembed")

    class _FakeModel:
        def __init__(self, model_name=None):
            self.model_name = model_name

        def embed(self, texts):
            for _ in texts:
                yield [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

    fake_emb.TextEmbedding = _FakeModel
    monkeypatch.setitem(sys.modules, "fastembed", fake_emb)
    # Reset the cache so the new fake gets picked up.
    from maverick.tools import embeddings as embmod
    embmod._model_cache.clear()

    out = embmod.embeddings().fn({"op": "embed", "text": "hello"})
    assert "dim=10" in out
    assert "0.1000" in out


def test_embeddings_similarity_cosine(monkeypatch):
    fake_emb = types.ModuleType("fastembed")

    class _FakeModel:
        def __init__(self, model_name=None):
            self._next = 0

        def embed(self, texts):
            for _ in texts:
                # Deterministic but distinct vectors per call.
                self._next += 1
                if self._next % 2 == 1:
                    yield [1.0, 0.0]
                else:
                    yield [1.0, 0.0]  # identical -> cosine 1.0

    fake_emb.TextEmbedding = _FakeModel
    monkeypatch.setitem(sys.modules, "fastembed", fake_emb)
    from maverick.tools import embeddings as embmod
    embmod._model_cache.clear()

    out = embmod.embeddings().fn(
        {"op": "similarity", "text_a": "x", "text_b": "y"},
    )
    assert "cosine = 1.0000" in out


def test_embeddings_rank_orders_by_similarity(monkeypatch):
    fake_emb = types.ModuleType("fastembed")
    # Return [1,0] for query, [1,0]/[0,1]/[0.5,0.5] for the candidates.
    sequence = iter([
        [1.0, 0.0],     # query
        [1.0, 0.0],     # candidate 0 (perfect match)
        [0.0, 1.0],     # candidate 1 (orthogonal)
        [0.5, 0.5],     # candidate 2 (mid)
    ])

    class _FakeModel:
        def __init__(self, model_name=None):
            pass

        def embed(self, texts):
            for _ in texts:
                yield next(sequence)

    fake_emb.TextEmbedding = _FakeModel
    monkeypatch.setitem(sys.modules, "fastembed", fake_emb)
    from maverick.tools import embeddings as embmod
    embmod._model_cache.clear()

    out = embmod.embeddings().fn({
        "op": "rank", "query": "q",
        "candidates": ["a", "b", "c"], "top_k": 3,
    })
    lines = [line for line in out.splitlines() if line.strip()]
    # First line should be candidate 0 (cosine 1.0).
    assert "#0" in lines[0]
    # Last should be candidate 1 (cosine 0.0).
    assert "#1" in lines[-1]


# ---------- provider health ----------

def test_provider_health_records_calls():
    from maverick.provider_health import ProviderHealth
    ph = ProviderHealth()
    ph.record("openai", "gpt-5", latency_ms=120, dollars=0.001)
    ph.record("openai", "gpt-5", latency_ms=200, dollars=0.002)
    ph.record("openai", "gpt-5", latency_ms=180, dollars=0.001, error=True)

    snap = ph.snapshot()
    assert len(snap) == 1
    row = snap[0]
    assert row["provider"] == "openai"
    assert row["model"] == "gpt-5"
    assert row["calls"] == 3
    assert row["errors"] == 1
    assert abs(row["error_rate"] - (1 / 3)) < 1e-6
    assert row["p50_ms"] == 180.0  # median of [120, 200, 180]
    assert row["total_dollars"] > 0
    assert row["last_seen"] > 0


def test_provider_health_snapshot_sorts_by_calls():
    from maverick.provider_health import ProviderHealth
    ph = ProviderHealth()
    for _ in range(2):
        ph.record("a", "m1", latency_ms=10)
    for _ in range(5):
        ph.record("b", "m2", latency_ms=20)
    snap = ph.snapshot()
    assert [r["provider"] for r in snap] == ["b", "a"]


def test_provider_health_reset_clears():
    from maverick.provider_health import ProviderHealth
    ph = ProviderHealth()
    ph.record("x", "y", latency_ms=1)
    assert ph.snapshot()
    ph.reset()
    assert ph.snapshot() == []


def test_provider_health_singleton_is_shared():
    from maverick.provider_health import get
    a = get()
    b = get()
    assert a is b


# ---------- cost router ----------

def test_cost_router_disabled_returns_none(monkeypatch):
    monkeypatch.delenv("MAVERICK_COST_ROUTING", raising=False)
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", lambda: {})
    from maverick.cost_router import CostSignal, pick
    assert pick(CostSignal(role="proposer")) is None


def test_cost_router_picks_cheapest_available(monkeypatch):
    monkeypatch.setenv("MAVERICK_COST_ROUTING", "1")
    # Only deepseek key is set -> deepseek wins on cheapness.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds_x")
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", lambda: {})

    from maverick.cost_router import TIER_CHEAP, CostSignal, pick
    spec = pick(CostSignal(tier=TIER_CHEAP))
    assert spec is not None
    assert spec.startswith("deepseek:")


def test_cost_router_falls_back_when_no_provider_configured(monkeypatch):
    monkeypatch.setenv("MAVERICK_COST_ROUTING", "1")
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
              "MOONSHOT_API_KEY", "XAI_API_KEY", "GROK_API_KEY",
              "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", lambda: {})

    from maverick.cost_router import CostSignal, pick
    # When no provider has usable credentials, the picker returns None so
    # model_for_role() defers to the role defaults. Picking a provider we
    # have no key for would only blow up later at client construction.
    spec = pick(CostSignal())
    assert spec is None


def test_cost_router_avoids_high_error_provider(monkeypatch):
    monkeypatch.setenv("MAVERICK_COST_ROUTING", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k1")
    monkeypatch.setenv("OPENAI_API_KEY", "k2")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", lambda: {})

    # Poison deepseek with errors. With penalty factor (1 + 5 * 1.0) = 6x
    # cost surcharge, even DeepSeek's cheapness should be overridden.
    from maverick.provider_health import get as _h
    # Use the real singleton — reset it so we can install our pattern.
    ph = _h()
    ph.reset()
    for _ in range(10):
        ph.record("deepseek", "deepseek-chat",
                  latency_ms=100, error=True)
    try:
        from maverick.cost_router import TIER_CHEAP, CostSignal, pick
        spec = pick(CostSignal(tier=TIER_CHEAP))
        assert spec is not None
        # Errored model itself should not be the pick (within-brand
        # swap to a non-errored model is acceptable).
        assert spec != "deepseek:deepseek-chat"
    finally:
        ph.reset()


# ---------- LLM call records provider health ----------

def test_llm_complete_records_provider_health(monkeypatch):
    """A successful LLM call updates provider_health."""
    from maverick.budget import Budget
    from maverick.llm import LLM
    from maverick.provider_health import get as _h

    _h().reset()

    class _FakeResp:
        text = "ok"
        thinking = None
        tool_calls = []
        stop_reason = "end_turn"
        cache_creation_tokens = 0
        cache_read_tokens = 0
        raw = None
        thinking_blocks = []
        thinking_signature = None

    class _FakeClient:
        def complete(self, **kwargs):
            time.sleep(0.005)
            return _FakeResp()

    llm = LLM(model="anthropic:claude-haiku-4-5-20251001",
              api_key="dummy")
    monkeypatch.setattr(llm, "_get_client", lambda provider: _FakeClient())

    budget = Budget(max_dollars=1.0)
    llm.complete(system="s", messages=[{"role": "user", "content": "hi"}],
                 budget=budget)
    snap = _h().snapshot()
    assert len(snap) == 1
    assert snap[0]["provider"] == "anthropic"
    assert snap[0]["calls"] == 1
    assert snap[0]["errors"] == 0
    assert snap[0]["p50_ms"] is not None


def test_llm_complete_records_error(monkeypatch):
    from maverick.llm import LLM
    from maverick.provider_health import get as _h

    _h().reset()

    class _Boom:
        def complete(self, **kwargs):
            raise RuntimeError("provider down")

    llm = LLM(model="anthropic:claude-haiku-4-5-20251001",
              api_key="dummy")
    monkeypatch.setattr(llm, "_get_client", lambda provider: _Boom())

    try:
        llm.complete(system="s", messages=[{"role": "user", "content": "x"}])
    except RuntimeError:
        pass
    snap = _h().snapshot()
    assert len(snap) == 1
    assert snap[0]["errors"] == 1


# ---------- registration smoke ----------

def test_gitlab_and_embeddings_register(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    assert "gitlab" in names
    assert "embeddings" in names


def test_local_backend_strips_gitlab_token(monkeypatch, tmp_path):
    from maverick.sandbox.local import LocalBackend
    monkeypatch.setenv("GITLAB_TOKEN", "glpat_test_secret")
    sb = LocalBackend(workdir=tmp_path)
    out = sb.exec("printf %s \"${GITLAB_TOKEN:-missing}\"")
    assert out.exit_code == 0
    assert out.stdout == "missing"
