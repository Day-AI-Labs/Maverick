"""Semantic cross-run recall over the vector_store adapters (#432).

The heavy backends (chromadb/qdrant) aren't installed in CI, so the wiring
is exercised with a FakeStore implementing the same add/query/delete
interface, injected via the `store=` parameter. The orchestrator path is
covered by monkeypatching semantic_recall.build_store.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from maverick import semantic_recall as sr
from maverick.budget import Budget
from maverick.orchestrator import _maybe_recall_prior_work, run_goal
from maverick.sandbox import LocalBackend
from maverick.world_model import WorldModel


class FakeStore:
    """In-memory stand-in for ChromaStore/QdrantStore.

    Ranks by token-overlap so tests are deterministic without embeddings;
    returns the same {id, document, distance, metadata} shape.
    """

    def __init__(self):
        self.docs: dict[str, tuple[str, dict]] = {}

    def add(self, documents, *, ids=None, metadatas=None):
        for i, doc in enumerate(documents):
            self.docs[ids[i]] = (doc, (metadatas or [{}])[i])

    def delete(self, ids):
        for i in ids:
            self.docs.pop(i, None)

    def count(self):
        return len(self.docs)

    def query(self, text, *, top_k=5):
        q = set(text.lower().split())
        scored = []
        for doc_id, (doc, meta) in self.docs.items():
            d = set(doc.lower().split())
            overlap = len(q & d) / len(q | d) if (q | d) else 0.0
            scored.append((overlap, doc_id, doc, meta))
        scored.sort(key=lambda r: r[0], reverse=True)
        out = []
        for overlap, doc_id, doc, meta in scored[:top_k]:
            out.append({
                "id": doc_id, "document": doc,
                "distance": 1.0 - overlap, "metadata": meta,
            })
        return out


class _Goal:
    def __init__(self, gid, title, description="", status="done", result=""):
        self.id = gid
        self.title = title
        self.description = description
        self.status = status
        self.result = result


class TestBackendName:
    def test_none_by_default(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_VECTOR_STORE", raising=False)
        assert sr.backend_name() is None

    def test_env_selects_backend(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_VECTOR_STORE", "chroma")
        assert sr.backend_name() == "chroma"

    def test_unknown_backend_is_none(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_VECTOR_STORE", "pinecone")
        assert sr.backend_name() is None

    def test_weaviate_backend_recognized(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_VECTOR_STORE", "weaviate")
        assert sr.backend_name() == "weaviate"


class TestIndexAndSearch:
    def test_index_then_search_finds_goal(self):
        store = FakeStore()
        sr.index_goal(_Goal(1, "deploy the web app", result="used docker"), store=store)
        hits = sr.search("deploy the web app", store=store)
        assert hits is not None
        assert hits[0][1]["goal_id"] == 1
        # Sensitive fields are NOT duplicated into the vector store's metadata --
        # callers hydrate title/result from the sealed world DB by goal_id.
        assert "result" not in hits[0][1]
        assert "title" not in hits[0][1]

    def test_index_omits_sensitive_metadata(self):
        store = FakeStore()
        sr.index_goal(_Goal(1, "deploy app", result="SECRET 4111111111111111"),
                      store=store)
        # The stored metadata holds no verbatim copy of the sensitive result.
        _doc, meta = store.docs["goal:1"]
        assert "4111111111111111" not in str(meta)
        assert set(meta) <= {"goal_id", "status"}

    def test_index_upserts_not_duplicates(self):
        store = FakeStore()
        g = _Goal(1, "summarize sales", result="v1")
        sr.index_goal(g, store=store)
        g.result = "v2"
        sr.index_goal(g, store=store)
        assert store.count() == 1
        hits = sr.search("summarize sales", store=store)
        assert hits[0][1]["goal_id"] == 1

    def test_search_excludes_current_goal(self):
        store = FakeStore()
        sr.index_goal(_Goal(7, "unique task alpha", result="done"), store=store)
        hits = sr.search("unique task alpha", store=store, exclude_goal_id=7)
        assert hits == []

    def test_search_returns_none_without_backend(self):
        # No store passed + no backend configured -> None (signals fallback).
        assert sr.search("anything") is None

    def test_index_noop_without_backend(self):
        assert sr.index_goal(_Goal(1, "x")) is False

    def test_distance_maps_to_similarity(self):
        store = FakeStore()
        sr.index_goal(_Goal(1, "alpha beta gamma", result="r"), store=store)
        hits = sr.search("alpha beta gamma", store=store)
        # Identical text -> overlap 1.0 -> distance 0.0 -> similarity ~1.0.
        assert hits[0][0] == pytest.approx(1.0)


class TestOrchestratorRouting:
    def test_recall_uses_semantic_when_available(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_AUTO_RECALL", "1")
        store = FakeStore()
        monkeypatch.setattr(sr, "build_store", lambda backend=None: store)
        world = WorldModel(tmp_path / "w.db")
        # The prior goal is a REAL world goal (title/result come from the sealed
        # DB now, not from vector metadata); index that world goal.
        prior = world.create_goal("build a sales CSV report", "group + sum")
        world.set_goal_status(prior, "done", result="wrote report.csv")
        sr.index_goal(world.get_goal(prior), store=store)
        cur = world.get_goal(
            world.create_goal("build a sales CSV report v2", "group + sum")
        )
        block = _maybe_recall_prior_work(world, cur, None)
        assert block is not None
        assert "Relevant prior work" in block
        assert "wrote report.csv" in block

    def test_recall_falls_back_when_no_backend(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_AUTO_RECALL", "1")
        monkeypatch.setattr(sr, "build_store", lambda backend=None: None)
        world = WorldModel(tmp_path / "w.db")
        gid = world.create_goal("translate a document to French", "fr")
        world.set_goal_status(gid, "done", result="translated via tool")
        cur = world.get_goal(
            world.create_goal("translate a document to French again", "fr")
        )
        # Falls back to recall_past_goals (lexical) and still finds the prior.
        block = _maybe_recall_prior_work(world, cur, None)
        assert block is not None
        assert "translated via tool" in block


@pytest.mark.asyncio
async def test_run_goal_indexes_on_success(tmp_path: Path, fake_llm, make_llm_response, monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(sr, "build_store", lambda backend=None: store)
    fake_llm.scripted = [
        make_llm_response(text="FINAL: done"),
        make_llm_response(
            text='{"confidence": 0.95, "accepts": true, "critique": "ok", "issues": []}',
        ),
        make_llm_response(text="FINAL: (no skill)"),
    ]
    world = WorldModel(path=tmp_path / "world.db")
    gid = world.create_goal("index me on success", "please")
    await run_goal(
        llm=fake_llm, world=world, budget=Budget(max_dollars=1.0),
        goal_id=gid, sandbox=LocalBackend(workdir=tmp_path), max_depth=1,
    )
    # The finished goal was indexed into the semantic store.
    assert store.count() == 1
    hits = sr.search("index me on success", store=store)
    assert hits[0][1]["goal_id"] == gid


class TestTenantCollectionIsolation:
    """build_store gives each tenant its OWN collection on the shared external
    backends (chroma/qdrant/weaviate) so similarity SEARCH can't cross tenants.
    """

    def _capture(self, monkeypatch):
        import maverick.vector_store as vs
        captured = {}

        class _Fake:
            def __init__(self, collection=None, **kw):
                captured["collection"] = collection

        monkeypatch.setattr(vs, "ChromaStore", _Fake)
        monkeypatch.setattr(vs, "QdrantStore", _Fake)
        monkeypatch.setattr(vs, "WeaviateStore", _Fake)
        return captured

    def test_collection_is_tenant_namespaced(self, monkeypatch):
        captured = self._capture(monkeypatch)
        from maverick import paths
        monkeypatch.setattr(paths, "current_tenant", lambda: "acme-1")

        sr.build_store("chroma")
        assert captured["collection"] == "t_acme_1__goals"
        sr.build_store("qdrant")
        assert captured["collection"] == "t_acme_1__goals"
        sr.build_store("weaviate")  # class names must start uppercase
        assert captured["collection"] == "T_acme_1__Goals"

    def test_single_tenant_collection_unchanged(self, monkeypatch):
        captured = self._capture(monkeypatch)
        from maverick import paths
        monkeypatch.setattr(paths, "current_tenant", lambda: None)

        sr.build_store("chroma")
        assert captured["collection"] == "goals"
        sr.build_store("weaviate")
        assert captured["collection"] == "Goals"

    def test_two_tenants_get_distinct_collections(self, monkeypatch):
        captured = self._capture(monkeypatch)
        from maverick import paths

        monkeypatch.setattr(paths, "current_tenant", lambda: "tenant_a")
        sr.build_store("qdrant")
        a = captured["collection"]
        monkeypatch.setattr(paths, "current_tenant", lambda: "tenant_b")
        sr.build_store("qdrant")
        b = captured["collection"]
        assert a != b and a == "t_tenant_a__goals" and b == "t_tenant_b__goals"
