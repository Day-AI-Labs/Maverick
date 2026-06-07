"""Per-domain document knowledge (vector RAG) for Maverick agents.

The pure core works with no extra deps (``DeterministicEmbedder`` +
``SqliteVectorStore`` + text/markdown/HTML parsing). Hosted/local embedders,
PDF/DOCX parsers, and pgvector are opt-in extras. Off by default; the agent
kernel never requires this package.
"""
from .base import Hit, KnowledgeBase
from .chunk import chunk_text
from .embed import DeterministicEmbedder, HostedEmbedder, build_embedder
from .store import SqliteVectorStore, build_store

__version__ = "0.1.0"
__all__ = [
    "KnowledgeBase",
    "Hit",
    "chunk_text",
    "DeterministicEmbedder",
    "HostedEmbedder",
    "build_embedder",
    "SqliteVectorStore",
    "build_store",
]
