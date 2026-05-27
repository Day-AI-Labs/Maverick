"""Tests for the Qdrant vector store adapter.

qdrant-client is an optional dep; we test both the missing-import path
and the wired-up path with a mock client.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_qdrant_missing_import_raises(monkeypatch):
    """No qdrant-client installed -> actionable ImportError."""
    monkeypatch.setitem(sys.modules, "qdrant_client", None)
    from maverick.vector_store.qdrant_store import QdrantStore
    with pytest.raises(ImportError, match="qdrant-client not installed"):
        QdrantStore()


def _install_fake_qdrant(monkeypatch) -> MagicMock:
    """Replace ``qdrant_client`` with a stub. Returns the fake client instance."""
    fake_client = MagicMock(name="QdrantClient instance")
    fake_module = MagicMock(name="qdrant_client module")
    fake_module.QdrantClient = MagicMock(return_value=fake_client)
    fake_models = MagicMock(name="qdrant_client.models module")

    class _PointIdsList:
        def __init__(self, points):
            self.points = points

    fake_models.PointIdsList = _PointIdsList
    monkeypatch.setitem(sys.modules, "qdrant_client", fake_module)
    monkeypatch.setitem(sys.modules, "qdrant_client.models", fake_models)
    return fake_client


def test_qdrant_local_path_init(monkeypatch, tmp_path):
    fake_client = _install_fake_qdrant(monkeypatch)
    monkeypatch.delenv("MAVERICK_QDRANT_URL", raising=False)

    from maverick.vector_store.qdrant_store import QdrantStore
    store = QdrantStore(path=tmp_path / "qd")
    assert store is not None
    assert (tmp_path / "qd").exists()
    assert fake_client is not None  # client constructed


def test_qdrant_url_init_skips_path(monkeypatch, tmp_path):
    _install_fake_qdrant(monkeypatch)
    monkeypatch.setenv("MAVERICK_QDRANT_URL", "http://example:6333")
    monkeypatch.setenv("MAVERICK_QDRANT_API_KEY", "secret")
    from maverick.vector_store.qdrant_store import QdrantStore
    # Should not raise -- url path bypasses local dir creation.
    QdrantStore()
    import qdrant_client
    qdrant_client.QdrantClient.assert_called_with(
        url="http://example:6333", api_key="secret",
    )


def test_qdrant_add_autogenerates_ids(monkeypatch, tmp_path):
    fake_client = _install_fake_qdrant(monkeypatch)
    monkeypatch.delenv("MAVERICK_QDRANT_URL", raising=False)
    from maverick.vector_store.qdrant_store import QdrantStore
    store = QdrantStore(path=tmp_path / "qd")
    store.add(["doc1", "doc2"])
    fake_client.add.assert_called_once()
    kwargs = fake_client.add.call_args.kwargs
    assert kwargs["documents"] == ["doc1", "doc2"]
    assert len(kwargs["ids"]) == 2
    assert all(isinstance(i, str) for i in kwargs["ids"])


def test_qdrant_add_passes_metadata(monkeypatch, tmp_path):
    fake_client = _install_fake_qdrant(monkeypatch)
    monkeypatch.delenv("MAVERICK_QDRANT_URL", raising=False)
    from maverick.vector_store.qdrant_store import QdrantStore
    store = QdrantStore(path=tmp_path / "qd")
    store.add(["doc"], ids=["x"], metadatas=[{"src": "test"}])
    kwargs = fake_client.add.call_args.kwargs
    assert kwargs["metadata"] == [{"src": "test"}]
    assert kwargs["ids"] == ["x"]


def test_qdrant_add_empty_noop(monkeypatch, tmp_path):
    fake_client = _install_fake_qdrant(monkeypatch)
    monkeypatch.delenv("MAVERICK_QDRANT_URL", raising=False)
    from maverick.vector_store.qdrant_store import QdrantStore
    store = QdrantStore(path=tmp_path / "qd")
    store.add([])
    fake_client.add.assert_not_called()


def test_qdrant_query_shape(monkeypatch, tmp_path):
    fake_client = _install_fake_qdrant(monkeypatch)
    monkeypatch.delenv("MAVERICK_QDRANT_URL", raising=False)
    fake_client.query.return_value = [
        SimpleNamespace(id="a", document="doc-a", score=0.9, metadata={"k": 1}),
        SimpleNamespace(id="b", document="doc-b", score=0.4, metadata=None),
    ]
    from maverick.vector_store.qdrant_store import QdrantStore
    store = QdrantStore(path=tmp_path / "qd")
    out = store.query("hello", top_k=2)
    assert len(out) == 2
    assert out[0]["id"] == "a"
    assert out[0]["document"] == "doc-a"
    assert out[0]["distance"] == pytest.approx(0.1, abs=1e-6)
    assert out[1]["metadata"] is None


def test_qdrant_query_empty_text(monkeypatch, tmp_path):
    _install_fake_qdrant(monkeypatch)
    monkeypatch.delenv("MAVERICK_QDRANT_URL", raising=False)
    from maverick.vector_store.qdrant_store import QdrantStore
    store = QdrantStore(path=tmp_path / "qd")
    assert store.query("") == []


def test_qdrant_delete(monkeypatch, tmp_path):
    fake_client = _install_fake_qdrant(monkeypatch)
    monkeypatch.delenv("MAVERICK_QDRANT_URL", raising=False)
    from maverick.vector_store.qdrant_store import QdrantStore
    store = QdrantStore(path=tmp_path / "qd")
    store.delete(["a", "b"])
    fake_client.delete.assert_called_once()
    # PointIdsList stub carries the points list:
    kwargs = fake_client.delete.call_args.kwargs
    assert kwargs["collection_name"] == "maverick"
    assert kwargs["points_selector"].points == ["a", "b"]


def test_qdrant_count(monkeypatch, tmp_path):
    fake_client = _install_fake_qdrant(monkeypatch)
    monkeypatch.delenv("MAVERICK_QDRANT_URL", raising=False)
    fake_client.count.return_value = SimpleNamespace(count=42)
    from maverick.vector_store.qdrant_store import QdrantStore
    store = QdrantStore(path=tmp_path / "qd")
    assert store.count() == 42


def test_qdrant_count_swallows_errors(monkeypatch, tmp_path):
    fake_client = _install_fake_qdrant(monkeypatch)
    monkeypatch.delenv("MAVERICK_QDRANT_URL", raising=False)
    fake_client.count.side_effect = RuntimeError("no collection")
    from maverick.vector_store.qdrant_store import QdrantStore
    store = QdrantStore(path=tmp_path / "qd")
    assert store.count() == 0
