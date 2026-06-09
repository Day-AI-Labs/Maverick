"""Governed self-evolution for Maverick (Stages 0-2: eval, archive, search).

Code self-modification is deliberately NOT here -- see the package README and
docs/research/. Everything in this package is opt-in and pure/DI so it is
testable without a live model.
"""
from __future__ import annotations

from . import config_space
from .agent_adapter import evolve_live, make_agent_factory
from .archive import Archive, Candidate
from .eval_harness import EvalCase, EvalReport, evaluate
from .loop import evolve_continuous
from .runner import EvolutionFrozen, calibration_frozen, evolve_with_eval
from .search import evolve

__all__ = [
    "EvalCase",
    "EvalReport",
    "evaluate",
    "Archive",
    "Candidate",
    "evolve",
    "config_space",
    "evolve_with_eval",
    "evolve_continuous",
    "evolve_live",
    "make_agent_factory",
    "calibration_frozen",
    "EvolutionFrozen",
]
