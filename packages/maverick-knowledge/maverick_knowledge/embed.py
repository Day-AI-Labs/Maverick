"""Embedding providers.

Config-selected (``hosted`` | ``local`` | ``deterministic``), default ``hosted``.
:func:`build_embedder` **fails loud**: a chosen provider that can't initialize
raises rather than silently degrading to the non-semantic
:class:`DeterministicEmbedder` (which returns plausible-looking but meaningless
retrievals). Opt into the hash embedder explicitly with
``embedder = "deterministic"`` for tests / offline dev.
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
                h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest(), 16)
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
        # OpenAI/Voyage-compatible responses are only guaranteed addressable by
        # each item's `index`, not positional order, so reorder before zipping
        # vectors back to their input chunks (a reordered batch would otherwise
        # pair chunk text with the wrong vector and silently corrupt the index).
        data = sorted(r.json()["data"], key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]


def build_embedder(cfg: dict | None = None) -> Embedder:
    """Select an embedder from config. **Fails loud.**

    A configured provider that can't initialize (``hosted`` with no API key,
    ``local`` without the extra) raises rather than silently falling back to the
    non-semantic :class:`DeterministicEmbedder` -- a silent downgrade yields
    plausible-looking but meaningless retrievals a business would unknowingly
    trust. The hash embedder must be opted into: ``embedder = "deterministic"``
    (or ``MAVERICK_EMBED_PROVIDER=deterministic``), used by tests / offline dev.
    """
    cfg = cfg or {}
    # The env var is an operator escape hatch that wins over config -- e.g. to
    # force offline/deterministic retrieval without editing config.toml.
    provider = str(
        os.environ.get("MAVERICK_EMBED_PROVIDER") or cfg.get("embedder", "hosted")
    ).lower()

    if provider == "deterministic":
        return DeterministicEmbedder(int(cfg.get("dim", 256)))

    if provider == "hosted":
        key = cfg.get("api_key") or os.environ.get("MAVERICK_EMBED_API_KEY", "")
        if not key:
            raise RuntimeError(
                "knowledge: hosted embedder selected but no API key (set "
                "[knowledge] api_key or MAVERICK_EMBED_API_KEY); or set "
                "embedder = 'deterministic' for offline/dev retrieval."
            )
        return HostedEmbedder(
            model=cfg.get("model", "voyage-3"),
            base_url=cfg.get("base_url", "https://api.voyageai.com/v1"),
            api_key=key,
            dim=int(cfg.get("dim", 1024)),
        )

    if provider == "local":
        import importlib.util
        if importlib.util.find_spec("sentence_transformers") is None:
            raise RuntimeError(
                "knowledge: local embedder selected but sentence-transformers is "
                "not installed (the 'local' extra); or set "
                "embedder = 'deterministic' for offline/dev retrieval."
            )
        from .local_embed import LocalEmbedder  # optional 'local' extra
        return LocalEmbedder(cfg.get("model", "all-MiniLM-L6-v2"))

    raise ValueError(
        f"knowledge: unknown embedder provider {provider!r} "
        "(expected 'hosted', 'local', or 'deterministic')."
    )
