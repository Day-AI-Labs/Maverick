"""Embedding providers.

Config-selected (``hosted`` | ``local`` | ``deterministic``); default hosted with
a safe fallback to the dependency-free :class:`DeterministicEmbedder`, so the
knowledge layer works out of the box (and in tests) with no API key or heavy
local model.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
from typing import Protocol

log = logging.getLogger(__name__)


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _l2(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


class DeterministicEmbedder:
    """Dependency-free hashing embedder.

    NOT semantic -- a deterministic bag-of-hashed-tokens vector so the pipeline
    runs (and tests pass) with no API key or model download. Same text -> same
    vector; lexically-overlapping texts land near each other, which is enough to
    exercise and verify the retrieval plumbing.
    """

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in (t or "").lower().split():
                h = int(hashlib.sha1(tok.encode("utf-8")).hexdigest(), 16)
                v[h % self.dim] += 1.0
            out.append(_l2(v))
        return out


class HostedEmbedder:
    """Voyage / OpenAI-compatible embeddings over HTTP (needs an API key).

    Voyage is Anthropic's recommended embeddings partner; any OpenAI-compatible
    ``/embeddings`` endpoint also works via ``base_url`` + ``model``. ``httpx``
    is imported lazily so the package imports clean without the ``hosted`` extra.
    """

    def __init__(self, model: str, base_url: str, api_key: str, dim: int = 1024):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        r = httpx.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts},
            timeout=60,
        )
        r.raise_for_status()
        return [d["embedding"] for d in r.json()["data"]]


def build_embedder(cfg: dict | None = None) -> Embedder:
    """Select an embedder from config, falling back to ``DeterministicEmbedder``
    when the chosen provider can't initialize (no key / extra not installed), so
    enabling knowledge never hard-fails setup."""
    cfg = cfg or {}
    provider = str(cfg.get("embedder", "hosted")).lower()
    try:
        if provider == "hosted":
            key = cfg.get("api_key") or os.environ.get("MAVERICK_EMBED_API_KEY", "")
            if not key:
                raise RuntimeError("no embeddings API key configured")
            return HostedEmbedder(
                model=cfg.get("model", "voyage-3"),
                base_url=cfg.get("base_url", "https://api.voyageai.com/v1"),
                api_key=key,
                dim=int(cfg.get("dim", 1024)),
            )
        if provider == "local":
            from .local_embed import LocalEmbedder  # optional 'local' extra
            return LocalEmbedder(cfg.get("model", "all-MiniLM-L6-v2"))
    except Exception as e:
        log.warning(
            "knowledge: %s embedder unavailable (%s); using deterministic fallback",
            provider, e,
        )
    return DeterministicEmbedder(int(cfg.get("dim", 256)))
