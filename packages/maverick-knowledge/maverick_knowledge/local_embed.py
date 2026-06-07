"""Local sentence-transformers embedder (the optional ``local`` extra).

Selected by ``[knowledge] embedder = "local"``. The model is loaded lazily on
first use so importing the package stays cheap and dependency-free; the heavy
``sentence-transformers`` dependency ships in the ``local`` extra. Vectors are
L2-normalized to match the other embedders so cosine ranking is consistent.
"""
from __future__ import annotations


class LocalEmbedder:
    """Embeds with a local sentence-transformers model (default MiniLM, 384-dim)."""

    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        self.model_name = model
        self._model = None
        # all-MiniLM-L6-v2 is 384-dim; refined from the model once it loads.
        self.dim = 384

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            reported = self._model.get_sentence_embedding_dimension()
            if reported:
                self.dim = int(reported)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        vectors = model.encode(list(texts), normalize_embeddings=True)
        return [[float(x) for x in v] for v in vectors]
