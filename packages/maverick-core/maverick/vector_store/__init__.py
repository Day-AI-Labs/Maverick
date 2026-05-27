"""Vector-store adapters for cross-run semantic memory.

Adapters share a minimal interface: ``add(docs)``, ``query(text)``,
``delete(ids)``, ``count()``. Each adapter is behind its own optional
extra; users install only what they need.

Currently:
  - ChromaStore (``maverick-agent[chroma]``) — local persistent
    embedding store at ~/.maverick/vector_store/ (chmod 700).
"""
from .chroma_store import ChromaStore, DEFAULT_PATH  # noqa: F401


__all__ = ["ChromaStore", "DEFAULT_PATH"]
