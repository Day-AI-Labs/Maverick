"""Tests for the batch-2 roadmap tools: semantic_code_search, mutation_test,
constrained_output."""
from __future__ import annotations

import textwrap

from maverick.tools.constrained_output import constrained_output
from maverick.tools.mutation_test import mutation_test
from maverick.tools.semantic_code_search import semantic_code_search

# ---- semantic_code_search ----

def test_search_ranks_by_intent(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text(textwrap.dedent('''
        def parse_csv_file(path):
            """Read a CSV file and return rows."""
            return []

        def send_email(to, body):
            """Deliver an email message to a recipient."""
            return True
    '''))
    t = semantic_code_search()
    out = t.fn({"op": "search", "paths": [str(f)], "query": "read csv rows from file"})
    top = out.splitlines()[0]
    assert "parse_csv_file" in top and "send_email" not in top


def test_search_splits_camel_and_snake(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def loadUserProfile():\n    pass\n")
    t = semantic_code_search()
    out = t.fn({"op": "search", "paths": [str(f)], "query": "load user profile"})
    assert "loadUserProfile" in out


def test_search_requires_query_and_paths():
    t = semantic_code_search()
    assert t.fn({"op": "search", "paths": [], "query": "x"}).startswith("ERROR")
    assert t.fn({"op": "search", "paths": ["/tmp"], "query": ""}).startswith("ERROR")


# ---- mutation_test ----

def test_mutants_cover_operators():
    t = mutation_test()
    src = "def f(a, b):\n    return a + b > 0 and b\n"
    out = t.fn({"op": "mutants", "source": src})
    assert "arithmetic: '+' -> '-'" in out
    assert "comparison: '>' -> '>='" in out
    assert "boolean: 'and' -> 'or'" in out
    assert "number: 0 -> 1" in out


def test_mutants_cap_and_empty():
    t = mutation_test()
    assert t.fn({"op": "mutants", "source": "x = 1 + 2 + 3 + 4", "max": 2}).startswith("2 mutant")
    assert "no mutants" in t.fn({"op": "mutants", "source": "x = 'hello'"})


def test_mutants_syntax_error():
    t = mutation_test()
    assert t.fn({"op": "mutants", "source": "def ("}).startswith("ERROR")


# ---- constrained_output ----

def test_constrained_type_coercion_and_range():
    t = constrained_output()
    assert t.fn({"value": "42", "schema": {"type": "integer"}}) == "PASS 42"
    assert t.fn({"value": "5", "schema": {"type": "integer", "maximum": 3}}).startswith("FAIL")
    assert t.fn({"value": "yes", "schema": {"type": "boolean"}}) == "PASS True"


def test_constrained_enum_and_pattern():
    t = constrained_output()
    assert t.fn({"value": "red", "schema": {"enum": ["red", "green"]}}) == "PASS 'red'"
    assert t.fn({"value": "blue", "schema": {"enum": ["red", "green"]}}).startswith("FAIL")
    ok = t.fn({"value": "a@b.com", "schema": {"type": "string", "pattern": r"^[^@]+@[^@]+$"}})
    assert ok.startswith("PASS")
    assert t.fn({"value": "nope", "schema": {"type": "string", "pattern": r"^\d+$"}}).startswith("FAIL")


def test_constrained_length_and_errors():
    t = constrained_output()
    assert t.fn({"value": "ab", "schema": {"type": "string", "min_length": 3}}).startswith("FAIL")
    assert t.fn({"schema": {"type": "string"}}).startswith("ERROR")  # missing value
    assert t.fn({"value": "x", "schema": {}}).startswith("ERROR")    # empty schema


# ---- registration ----

def test_batch2_tools_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        pass

    reg = base_registry(world=_W(), sandbox=_S())
    names = set(getattr(reg, "_tools", {}).keys())
    for n in ("semantic_code_search", "mutation_test", "constrained_output"):
        assert n in names, f"{n} not registered"
