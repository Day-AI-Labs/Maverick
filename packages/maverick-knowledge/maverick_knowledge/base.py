"""The knowledge engine: ingest documents into a per-domain collection and
retrieve relevant chunks.

Ingestion is shield-scanned so a poisoned document is caught at the door -- RAG
poisoning is precisely what the agent compartments defend against, so the
knowledge layer scans on the way in rather than only at query time.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from .chunk import chunk_text
from .embed import DeterministicEmbedder
from .parse import extract_text
from .store import SqliteVectorStore

log = logging.getLogger(__name__)


@dataclass
class Hit:
    score: float
    text: str
    source: str


class KnowledgeBase:
    """A per-domain document store.

    ``collection`` is the domain's knowledge source, so a finance agent's
    queries never surface legal's documents -- knowledge respects the same
    bulkheads the compartments enforce.
    """

    def __init__(self, store=None, embedder=None, shield=None,
                 chunk_size: int = 1000, chunk_overlap: int = 200):
        self.store = store or SqliteVectorStore()
        self.embedder = embedder or DeterministicEmbedder()
        self.shield = shield
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _safe(self, text: str) -> bool:
        """Shield-scan a chunk on the way in. Fail-open: a scanner error never
        blocks ingestion, mirroring the kernel's shield contract."""
        if self.shield is None:
            return True
        try:
            verdict = self.shield.scan_input(text)
            return getattr(verdict, "allowed", True)
        except Exception:  # pragma: no cover -- never block ingest on a scan bug
            return True

    def ingest_text(self, collection: str, text: str, source: str = "") -> int:
        """Chunk, shield-scan, embed and store one document's text. Returns the
        number of chunks stored (poisoned chunks are dropped)."""
        chunks = [
            c for c in chunk_text(text, self.chunk_size, self.chunk_overlap)
            if self._safe(c)
        ]
        if not chunks:
            return 0
        vectors = self.embedder.embed(chunks)
        items = [
            (uuid.uuid4().hex, c, v, {"source": source})
            for c, v in zip(chunks, vectors)
        ]
        self.store.add(collection, items)
        return len(items)

    def ingest_path(self, collection: str, path) -> int:
        """Ingest a document from disk (parsed by extension)."""
        return self.ingest_text(collection, extract_text(path), source=str(path))

    def search(self, collection: str, query: str, k: int = 5) -> list[Hit]:
        vector = self.embedder.embed([query])[0]
        return [
            Hit(m.score, m.text, m.meta.get("source", ""))
            for m in self.store.search(collection, vector, k)
        ]

    def search_formatted(self, collections, query: str, k: int = 5) -> str:
        """Search one or more domain collections and render the top-k chunks with
        their sources -- the string a domain agent's ``knowledge_search`` tool
        returns. Merges across collections, then keeps the globally top-k."""
        hits: list[Hit] = []
        for c in collections:
            hits.extend(self.search(c, query, k))
        hits.sort(key=lambda h: h.score, reverse=True)
        hits = hits[: max(1, k)]
        if not hits:
            return "No relevant documents found in this domain's knowledge base."
        return "\n\n".join(
            f"[source: {h.source or 'unknown'}]\n{h.text}" for h in hits
        )
