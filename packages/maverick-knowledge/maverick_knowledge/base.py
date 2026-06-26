"""The knowledge engine: ingest documents into a per-domain collection and
retrieve relevant chunks.

Ingestion is screened so a poisoned document is caught at the door -- RAG
poisoning is precisely what the agent compartments defend against, so the
knowledge layer scans on the way in rather than only at query time. A configured
Shield does the heavy lifting; a built-in high-signal injection-marker screen
ALWAYS runs too, so the common no-Shield default still rejects the obvious
prompt-injection payloads (mirrors fleet_memory / memory_guard, which screen
external writes regardless of whether a Shield is wired).
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass

from .chunk import chunk_text
from .embed import DeterministicEmbedder
from .parse import extract_text
from .store import SqliteVectorStore

log = logging.getLogger(__name__)

# Built-in injection tripwire applied to every ingested chunk, even when no
# Shield is configured. maverick-knowledge is standalone (no maverick-core dep),
# so it can't reuse memory_guard.injection_markers; this is a deliberately small,
# high-signal subset of the SAME phrases -- instruction-override, role-reassign,
# fake role tags, secret-exfiltration, and safety-override. The shell/base64
# patterns memory_guard also carries are intentionally OMITTED here: a knowledge
# base legitimately ingests engineering docs full of `rm -rf` / `curl` / base64,
# and silently dropping those would harm recall. A real Shield (when passed)
# covers the rest.
_INJECTION_RE = re.compile(
    r"\b(?:ignore|disregard|forget)\b.{0,30}\b(?:previous|prior|above|earlier|all)\b"
    r".{0,30}\b(?:instruction|message|context|prompt|rule)"
    r"|\byou\s+are\s+now\b"
    r"|\bnew\s+(?:system\s+)?(?:instruction|prompt|directive|rule)"
    r"|</?\s*(?:system|assistant|developer)\s*>"
    r"|\b(?:reveal|print|show|leak|exfiltrate)\b.{0,40}"
    r"\b(?:system\s+prompt|your\s+instruction|secret|api[\s_-]?key|password|token|credential)"
    r"|\boverride\b.{0,20}\b(?:safety|guard|shield|policy|governance)\b",
    re.IGNORECASE,
)


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
                 chunk_size: int = 1000, chunk_overlap: int = 200,
                 image_describer=None):
        self.store = store or SqliteVectorStore()
        self.embedder = embedder or DeterministicEmbedder()
        self.shield = shield
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        # Optional callable(path) -> str for images / process diagrams (OCR or a
        # vision model). Without it, image uploads are skipped (not read as bytes).
        self.image_describer = image_describer

    def close(self) -> None:
        """Release the backing store's resources (e.g. the SQLite connection).

        No-op for stores that don't expose ``close`` (e.g. a future pgvector
        pool managed elsewhere)."""
        closer = getattr(self.store, "close", None)
        if callable(closer):
            closer()

    def __enter__(self) -> KnowledgeBase:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _safe(self, text: str) -> bool:
        """Screen a chunk on the way in. The built-in injection-marker tripwire
        ALWAYS runs (even with no Shield wired, the common default), so a poisoned
        document can't ride into prompts via search_formatted. A configured Shield
        runs in addition. Fail-open ONLY on a Shield scanner error, mirroring the
        kernel's shield contract -- the marker screen itself never errors."""
        if _INJECTION_RE.search(text):
            log.warning("knowledge: dropping chunk with injection marker on ingest")
            return False
        if self.shield is None:
            return True
        try:
            # An ingested chunk is untrusted CONTENT (like tool output), so use
            # the indirect-injection / content detector, not the prompt-tuned
            # scan_input.
            verdict = self.shield.scan_output(text)
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
            for c, v in zip(chunks, vectors, strict=False)
        ]
        self.store.add(collection, items)
        return len(items)

    def ingest_path(self, collection: str, path) -> int:
        """Ingest a document from disk (parsed by extension).

        Images / process diagrams go through ``image_describer`` (OCR or a
        vision model); without one they're skipped rather than read as bytes.
        The resulting text is shield-scanned like any other document."""
        from .parse import is_image
        if is_image(path):
            if self.image_describer is None:
                log.info("knowledge: skipping image %s (no image_describer set)", path)
                return 0
            try:
                text = self.image_describer(str(path))
            except Exception as e:  # a describer failure must not abort ingestion
                log.warning("knowledge: image describer failed on %s: %s", path, e)
                return 0
        else:
            text = extract_text(path)
        return self.ingest_text(collection, text, source=str(path))

    def delete_collection(self, collection: str) -> None:
        """Delete an unapproved or retired collection from the backing store."""
        self.store.delete_collection(collection)

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
