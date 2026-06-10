"""Tests for the Weaviate vector store adapter.

weaviate-client is an optional dep; we test both the missing-import path and
the wired-up path with a mock client, mirroring test_qdrant_store.py.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


def test_weaviate_missing_import_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "weaviate", None)
    from maverick.vector_store.weaviate_store import WeaviateStore
    with pytest.raises(ImportError, match="weaviate-client not installed"):
        WeaviateStore()


def _install_fake_weaviate(monkeypatch, *, exists=False) -> tuple[MagicMock, MagicMock]:
    """Replace ``weaviate`` (+ submodules) with stubs. Returns (client, collection)."""
    collection = MagicMock(name="collection")
    client = MagicMock(name="client")
    client.collections.exists.return_value = exists
    client.collections.get.return_value = collection
    client.collections.create.return_value = collection

    fake = MagicMock(name="weaviate module")
    fake.connect_to_local.return_value = client
    fake.connect_to_weaviate_cloud.return_value = client

    init_mod = MagicMock(name="weaviate.classes.init")
    init_mod.Auth.api_key = MagicMock(side_effect=lambda k: f"auth:{k}")
    query_mod = MagicMock(name="weaviate.classes.query")
    query_mod.MetadataQuery = MagicMock(side_effect=lambda **kw: ("md", kw))

    monkeypatch.setitem(sys.modules, "weaviate", fake)
    monkeypatch.setitem(sys.modules, "weaviate.classes", MagicMock())
    monkeypatch.setitem(sys.modules, "weaviate.classes.init", init_mod)
    monkeypatch.setitem(sys.modules, "weaviate.classes.query", query_mod)
    return client, collection


def test_weaviate_local_init_creates_collection(monkeypatch):
    monkeypatch.delenv("MAVERICK_WEAVIATE_URL", raising=False)
    client, _ = _install_fake_weaviate(monkeypatch, exists=False)
    import weaviate
    from maverick.vector_store.weaviate_store import WeaviateStore
    WeaviateStore(collection="Maverick")
    weaviate.connect_to_local.assert_called_once()  # no URL -> local connect
    assert client.collections.create.called  # didn't exist -> created


def test_weaviate_cloud_init_uses_auth(monkeypatch):
    monkeypatch.setenv("MAVERICK_WEAVIATE_URL", "https://cluster.example")
    monkeypatch.setenv("MAVERICK_WEAVIATE_API_KEY", "secret")
    _install_fake_weaviate(monkeypatch, exists=True)
    import weaviate
    from maverick.vector_store.weaviate_store import WeaviateStore
    WeaviateStore()
    weaviate.connect_to_weaviate_cloud.assert_called_once()
    _, kwargs = weaviate.connect_to_weaviate_cloud.call_args
    assert kwargs["cluster_url"] == "https://cluster.example"
    assert kwargs["auth_credentials"] == "auth:secret"


def test_weaviate_add_inserts_with_stable_uuid(monkeypatch):
    monkeypatch.delenv("MAVERICK_WEAVIATE_URL", raising=False)
    _, collection = _install_fake_weaviate(monkeypatch, exists=True)
    from maverick.vector_store.weaviate_store import WeaviateStore
    store = WeaviateStore()
    store.add(["hello", "world"], ids=["a", "b"], metadatas=[{"src": "x"}, {"src": "y"}])
    assert collection.data.insert.call_count == 2
    _, kw = collection.data.insert.call_args_list[0]
    assert kw["properties"]["text"] == "hello" and kw["properties"]["src"] == "x"
    # Same logical id -> same UUIDv5 (idempotent).
    import uuid
    assert kw["uuid"] == str(uuid.uuid5(uuid.NAMESPACE_URL, "maverick:a"))


def test_weaviate_add_length_mismatch_raises(monkeypatch):
    monkeypatch.delenv("MAVERICK_WEAVIATE_URL", raising=False)
    _install_fake_weaviate(monkeypatch, exists=True)
    from maverick.vector_store.weaviate_store import WeaviateStore
    store = WeaviateStore()
    with pytest.raises(ValueError, match="ids length"):
        store.add(["a", "b"], ids=["only-one"])


def test_weaviate_query_maps_results(monkeypatch):
    monkeypatch.delenv("MAVERICK_WEAVIATE_URL", raising=False)
    _, collection = _install_fake_weaviate(monkeypatch, exists=True)

    obj = MagicMock()
    obj.uuid = "uuid-1"
    obj.properties = {"text": "refund policy", "src": "kb"}
    obj.metadata.distance = 0.12
    collection.query.near_text.return_value = MagicMock(objects=[obj])

    from maverick.vector_store.weaviate_store import WeaviateStore
    store = WeaviateStore()
    hits = store.query("refunds", top_k=3)
    assert hits == [{"id": "uuid-1", "document": "refund policy",
                     "distance": 0.12, "metadata": {"src": "kb"}}]
    assert store.query("") == []


def test_weaviate_count_and_delete(monkeypatch):
    monkeypatch.delenv("MAVERICK_WEAVIATE_URL", raising=False)
    _, collection = _install_fake_weaviate(monkeypatch, exists=True)
    collection.aggregate.over_all.return_value = MagicMock(total_count=7)

    from maverick.vector_store.weaviate_store import WeaviateStore
    store = WeaviateStore()
    assert store.count() == 7
    store.delete(["a"])
    assert collection.data.delete_by_id.called


def test_weaviate_exported_from_package(monkeypatch):
    from maverick.vector_store import WeaviateStore
    assert WeaviateStore is not None
