"""mutation_test: Python source mutant generator + malformed-arg robustness."""
from __future__ import annotations

from maverick.tools.mutation_test import mutation_test


def _fn():
    return mutation_test().fn


def test_basic_mutants():
    out = _fn()({"op": "mutants", "source": "x = a + b\n"})
    assert isinstance(out, str)
    assert not out.startswith("Traceback")


def test_non_string_source_does_not_crash():
    # Non-string source is coerced to str; must return a string, never raise.
    fn = _fn()
    for v in (5, 1.5, True, [1, 2, 3], {"a": 1}):
        out = fn({"op": "mutants", "source": v})
        assert isinstance(out, str)
        assert not out.startswith("Traceback")


def test_infinite_max_does_not_crash():
    out = _fn()({"op": "mutants", "source": "x = a + b\n", "max": float("inf")})
    assert isinstance(out, str)
    assert not out.startswith("Traceback")
