"""Execution backends. Local now; Docker / SSH / Modal later."""
from .local import LocalBackend, ExecResult

__all__ = ["LocalBackend", "ExecResult"]
