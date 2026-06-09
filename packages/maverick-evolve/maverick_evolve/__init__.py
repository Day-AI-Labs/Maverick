"""Governed self-evolution for Maverick (Stages 0-2: eval, archive, search).

Code self-modification is deliberately NOT here -- see the package README and
docs/research/. Everything in this package is opt-in and pure/DI so it is
testable without a live model.
"""
from __future__ import annotations

from .archive import Archive, Candidate
from .eval_harness import EvalCase, EvalReport, evaluate
from .search import evolve

__all__ = [
    "EvalCase",
    "EvalReport",
    "evaluate",
    "Archive",
    "Candidate",
    "evolve",
]
