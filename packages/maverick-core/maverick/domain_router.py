"""Specialist routing: rank packs by relevance to a task.

The roster is 1,118 specialists. ``list_specialists`` lets the orchestrator
drill down suite-by-suite, but there was no way to search the whole roster by
what the task actually IS -- so an ambiguous or cross-suite request forced the
model to guess the suite and browse it. This module is the deterministic
pre-filter: a dependency-free lexical retriever (weighted TF-IDF over each
pack's name, description, and persona) that narrows 1,118 packs to the handful
worth showing. The LLM still makes the final pick; it just picks from a relevant
shortlist instead of a haystack.

Pure and offline (no embeddings, no provider key), so it is testable and always
available. Embeddings would rank better on paraphrase and are a natural upgrade,
but the lexical baseline is what makes routing measurable today.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .domain import DomainProfile, available_domains

# Minimal stopword set: articles, pronouns, auxiliaries, and the words that
# appear in almost every persona (so they carry no routing signal). Deliberately
# small -- dropping a discriminative term ("review", "audit") would hurt.
_STOP = frozenset("""
a an the this that these those of for to in on at by with from into over under
and or but not no you your we our they it its is are be been being as do does
did have has had will would can could should may might must your you yours
i me my mine he she him her his hers them their there here what which who whom
specialist assistant business company companys agent pack draft drafts review
help helps team teams work works task tasks provide provides use uses make makes
""".split())

# Field weights -- a term in the pack NAME is the strongest routing signal, the
# description next, the persona last (it is long and dilutes).
_W_NAME, _W_DESC, _W_PERSONA = 4, 3, 1

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    out = []
    for tok in _TOKEN.findall((text or "").lower()):
        if tok in _STOP or len(tok) < 2:
            continue
        # light stemming: collapse a trailing plural 's' so "contracts"~"contract"
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


def _doc_terms(p: DomainProfile) -> Counter:
    """Field-weighted term frequencies for one pack."""
    tf: Counter = Counter()
    for tok in _tokens(p.name.replace("_", " ")):
        tf[tok] += _W_NAME
    for tok in _tokens(p.description):
        tf[tok] += _W_DESC
    for tok in _tokens(p.persona):
        tf[tok] += _W_PERSONA
    return tf


class DomainRouter:
    """A lexical TF-IDF index over the roster. Build once, query many times."""

    def __init__(self, domains: dict[str, DomainProfile]):
        self.names = sorted(domains)
        self._docs = {n: _doc_terms(domains[n]) for n in self.names}
        n_docs = max(len(self.names), 1)
        df: Counter = Counter()
        for tf in self._docs.values():
            df.update(tf.keys())
        # Smoothed IDF: a term in every pack ("finance") is near-zero; a rare term
        # ("escheatment") is high -- exactly the discriminative weighting we want.
        self._idf = {t: math.log((n_docs + 1) / (c + 1)) + 1.0 for t, c in df.items()}

    def rank(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """The top-``k`` packs for ``query`` as ``(name, score)``, best first.
        Scoreless (all-zero) results are dropped, so an off-roster query returns
        fewer than ``k`` rather than padding with noise."""
        q = _tokens(query)
        if not q:
            return []
        qw = {t: self._idf.get(t, 0.0) for t in set(q)}
        scored: list[tuple[str, float]] = []
        for name in self.names:
            tf = self._docs[name]
            s = sum(tf.get(t, 0) * w * w for t, w in qw.items())  # tf * idf^2
            if s > 0:
                scored.append((name, s))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:k]


_INDEX: DomainRouter | None = None
_INDEX_KEY: tuple | None = None


def rank_specialists(query: str, k: int = 10,
                     domains: dict[str, DomainProfile] | None = None) -> list[tuple[str, float]]:
    """Rank the enabled roster for ``query`` (cached index for the default roster)."""
    global _INDEX, _INDEX_KEY
    if domains is not None:
        return DomainRouter(domains).rank(query, k)
    doms = available_domains()
    key = tuple(sorted(doms))
    if _INDEX is None or key != _INDEX_KEY:
        _INDEX = DomainRouter(doms)
        _INDEX_KEY = key
    return _INDEX.rank(query, k)


__all__ = ["DomainRouter", "rank_specialists"]
