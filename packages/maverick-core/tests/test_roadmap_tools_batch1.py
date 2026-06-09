"""Tests for the batch-1 roadmap tools: knowledge_graph, citation_verifier,
cross_repo_deps, test_gen. Each is registered and behaves deterministically."""
from __future__ import annotations

import textwrap

from maverick.tools.citation_verifier import citation_verifier
from maverick.tools.cross_repo_deps import cross_repo_deps
from maverick.tools.knowledge_graph import knowledge_graph
from maverick.tools.test_gen import test_gen as make_test_gen

# ---- knowledge_graph ----

def test_kg_extract_structured_and_heuristic():
    t = knowledge_graph()
    out = t.fn({
        "op": "extract",
        "text": "Maverick uses Postgres. Orchestrator | spawns | sub-agents. "
                "The shield depends on the kernel.",
    })
    assert "Maverick | uses | Postgres" in out
    assert "Orchestrator | spawns | sub-agents" in out
    assert "shield | depends_on | kernel" in out


def test_kg_query_and_neighbors():
    t = knowledge_graph()
    triples = [["a", "uses", "b"], ["b", "uses", "c"], ["d", "is_a", "a"]]
    q = t.fn({"op": "query", "triples": triples, "relation": "uses"})
    assert "a --uses--> b" in q and "b --uses--> c" in q and "d --is_a--> a" not in q
    n = t.fn({"op": "neighbors", "triples": triples, "node": "a"})
    assert "a --uses--> b" in n and "d --is_a--> a" in n


def test_kg_dot_render():
    t = knowledge_graph()
    out = t.fn({"op": "dot", "triples": [["a", "uses", "b"]]})
    assert out.startswith("digraph knowledge {") and "'a' -> 'b'" in out


# ---- citation_verifier ----

def test_citation_supported_partial_unsupported():
    t = citation_verifier()
    src = "The quick brown fox jumps over the lazy dog near the river."
    out = t.fn({"items": [
        {"quote": "quick brown fox", "source": src},          # exact -> SUPPORTED
        {"quote": "the lazy dog jumps quick", "source": src},  # high overlap -> PARTIAL
        {"quote": "a spaceship landed", "source": src},        # -> UNSUPPORTED
    ]})
    lines = out.splitlines()
    assert lines[1].startswith("[0] SUPPORTED")
    assert lines[2].startswith("[1] PARTIAL")
    assert lines[3].startswith("[2] UNSUPPORTED")
    assert "1 supported, 1 partial, 1 unsupported of 3" in out


def test_citation_normalises_whitespace_and_case():
    t = citation_verifier()
    out = t.fn({"items": [{"quote": "QUICK   brown\nfox", "source": "the quick brown fox"}]})
    assert "[0] SUPPORTED" in out


# ---- cross_repo_deps ----

def _write(p, rel, body):
    f = p / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(textwrap.dedent(body))


def test_cross_repo_graph_and_cross_root(tmp_path):
    root_a = tmp_path / "repoA"
    root_b = tmp_path / "repoB"
    _write(root_a, "pkga/__init__.py", "")
    _write(root_a, "pkga/main.py", "import pkgb\n")          # cross-root edge
    _write(root_b, "pkgb/__init__.py", "")
    _write(root_b, "pkgb/util.py", "x = 1\n")
    t = cross_repo_deps()
    out = t.fn({"op": "graph", "paths": [str(root_a), str(root_b)]})
    assert "pkga -> pkgb" in out and "[cross-root]" in out


def test_cross_repo_cycles(tmp_path):
    root = tmp_path / "mono"
    _write(root, "p/__init__.py", "import q\n")
    _write(root, "q/__init__.py", "import p\n")
    t = cross_repo_deps()
    out = t.fn({"op": "cycles", "paths": [str(root)]})
    assert "p <-> q" in out or "q <-> p" in out


def test_cross_repo_requires_existing_dir():
    t = cross_repo_deps()
    assert t.fn({"op": "graph", "paths": ["/no/such/dir"]}).startswith("ERROR")


# ---- test_gen ----

def test_test_gen_infers_strategies_from_hints():
    t = make_test_gen()
    src = "def add(a: int, b: str) -> int:\n    return a\n"
    out = t.fn({"op": "hypothesis", "source": src})
    assert "from hypothesis import given, strategies as st" in out
    assert "a=st.integers()" in out
    assert "b=st.text()" in out
    assert "def test_add_properties(a, b):" in out
    assert "add(a=a, b=b)" in out


def test_test_gen_named_func_and_no_params():
    t = make_test_gen()
    src = "def first():\n    return 1\n\ndef second(x: bool):\n    return x\n"
    out = t.fn({"op": "hypothesis", "source": src, "func": "second"})
    assert "x=st.booleans()" in out and "test_second_properties" in out
    out2 = t.fn({"op": "hypothesis", "source": src, "func": "first"})
    assert "no params to fuzz" in out2 and "test_first_properties()" in out2


def test_test_gen_errors():
    t = make_test_gen()
    assert t.fn({"op": "hypothesis", "source": ""}).startswith("ERROR")
    assert t.fn({"op": "hypothesis", "source": "x = 1"}).startswith("ERROR")


# ---- registration ----

def test_batch1_tools_registered():
    from maverick.tools import base_registry

    class _FakeWorld:
        pass

    class _FakeSandbox:
        pass

    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())
    all_names = set(getattr(reg, "_tools", {}).keys())
    for n in ("knowledge_graph", "citation_verifier", "cross_repo_deps", "test_gen"):
        assert n in all_names, f"{n} not registered"
