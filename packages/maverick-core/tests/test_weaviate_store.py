"""Tests for the Weaviate vector store adapter.

weaviate-client is an optional dep; we test the missing-import path and the
wired-up path with a fake client, with no real backend.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_weaviate_missing_import_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "weaviate", None)
    from maverick.vector_store.weaviate_store import WeaviateStore
    with pytest.raises(ImportError, match="weaviate-client not installed"):
        WeaviateStore()


def _install_fake_weaviate(monkeypatch) -> MagicMock:
    fake_collection = MagicMock(name="collection")
    fake_collections = MagicMock(name="collections")
    fake_collections.exists.return_value = False
    fake_collections.get.return_value = fake_collection
    fake_client = MagicMock(name="weaviate client")
    fake_client.collections = fake_collections

    fake_module = MagicMock(name="weaviate module")
    fake_module.connect_to_embedded.return_value = fake_client
    fake_module.connect_to_local.return_value = fake_client
    fake_module.connect_to_weaviate_cloud.return_value = fake_client
    monkeypatch.setitem(sys.modules, "weaviate", fake_module)
    return fake_client


def test_weaviate_embedded_init_creates_collection(monkeypatch):
    monkeypatch.delenv("MAVERICK_WEAVIATE_URL", raising=False)
    monkeypatch.delenv("MAVERICK_WEAVIATE_VECTORIZER", raising=False)
    fake = _install_fake_weaviate(monkeypatch)
    from maverick.vector_store.weaviate_store import WeaviateStore
    WeaviateStore(collection="goals")
    # Capitalized class name, created because exists()==False, AND with a
    # server-side vectorizer configured (without it near_text cannot embed).
    fake.collections.create.assert_called_once()
    args, kwargs = fake.collections.create.call_args
    assert args[0] == "Goals"
    assert kwargs.get("vectorizer_config") is not None


def test_weaviate_vectorizer_none_skips_config(monkeypatch):
    monkeypatch.delenv("MAVERICK_WEAVIATE_URL", raising=False)
    fake = _install_fake_weaviate(monkeypatch)
    from maverick.vector_store.weaviate_store import WeaviateStore
    WeaviateStore(collection="goals", vectorizer="none")
    # Explicit opt-out: created with no vectorizer_config.
    fake.collections.create.assert_called_once_with("Goals")


def test_weaviate_uuid_for_is_stable():
    from maverick.vector_store.weaviate_store import _uuid_for
    assert _uuid_for("abc") == _uuid_for("abc")
    assert _uuid_for("abc") != _uuid_for("def")


def test_weaviate_add_batches(monkeypatch):
    monkeypatch.delenv("MAVERICK_WEAVIATE_URL", raising=False)
    fake = _install_fake_weaviate(monkeypatch)
    batch_cm = MagicMock()
    batch = MagicMock()
    batch_cm.__enter__.return_value = batch
    fake.collections.get.return_value.batch.dynamic.return_value = batch_cm
    from maverick.vector_store.weaviate_store import WeaviateStore
    store = WeaviateStore()
    store.add(["d1", "d2"], ids=["a", "b"])
    assert batch.add_object.call_count == 2


def test_weaviate_add_empty_noop(monkeypatch):
    monkeypatch.delenv("MAVERICK_WEAVIATE_URL", raising=False)
    _install_fake_weaviate(monkeypatch)
    from maverick.vector_store.weaviate_store import WeaviateStore
    store = WeaviateStore()
    store.add([])  # no raise, no batch


def test_weaviate_query_shape(monkeypatch):
    monkeypatch.delenv("MAVERICK_WEAVIATE_URL", raising=False)
    fake = _install_fake_weaviate(monkeypatch)
    obj = SimpleNamespace(
        uuid="u1",
        properties={"document": "hello", "src": "t"},
        metadata=SimpleNamespace(distance=0.25),
    )
    fake.collections.get.return_value.query.near_text.return_value = \
        SimpleNamespace(objects=[obj])
    from maverick.vector_store.weaviate_store import WeaviateStore
    out = WeaviateStore().query("hi", top_k=3)
    assert out[0]["document"] == "hello"
    assert out[0]["distance"] == pytest.approx(0.25)
    assert out[0]["score"] == pytest.approx(0.75)
    assert out[0]["metadata"] == {"src": "t"}


def test_weaviate_query_empty_text(monkeypatch):
    monkeypatch.delenv("MAVERICK_WEAVIATE_URL", raising=False)
    _install_fake_weaviate(monkeypatch)
    from maverick.vector_store.weaviate_store import WeaviateStore
    assert WeaviateStore().query("") == []


def test_weaviate_count(monkeypatch):
    monkeypatch.delenv("MAVERICK_WEAVIATE_URL", raising=False)
    fake = _install_fake_weaviate(monkeypatch)
    fake.collections.get.return_value.aggregate.over_all.return_value = \
        SimpleNamespace(total_count=7)
    from maverick.vector_store.weaviate_store import WeaviateStore
    assert WeaviateStore().count() == 7


def test_semantic_recall_recognizes_weaviate(monkeypatch):
    monkeypatch.setenv("MAVERICK_VECTOR_STORE", "weaviate")
    from maverick import semantic_recall
    assert semantic_recall.backend_name() == "weaviate"
