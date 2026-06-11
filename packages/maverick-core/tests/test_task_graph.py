"""Persistent task graph (ROADMAP 2027 H2)."""
from __future__ import annotations

import pytest
from maverick.task_graph import TaskGraph


def _g():
    g = TaskGraph()
    g.add_task("a", "first")
    g.add_task("b", "second", deps=["a"])
    g.add_task("c", "third", deps=["a"])
    g.add_task("d", "fourth", deps=["b", "c"])
    return g


def test_ready_is_the_frontier():
    g = _g()
    assert g.ready() == ["a"]  # only a has no deps
    g.set_status("a", "done")
    assert g.ready() == ["b", "c"]  # both unblocked
    g.set_status("b", "done")
    assert g.ready() == ["c"]  # d still waits on c


def test_topo_order_respects_deps():
    order = _g().topo_order()
    assert order.index("a") < order.index("b")
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


def test_cycle_detected_and_rejected():
    g = TaskGraph()
    g.add_task("x", deps=["y"])
    g.add_task("y", deps=["x"])
    assert g.has_cycle()
    with pytest.raises(ValueError):
        g.topo_order()


def test_self_dependency_rejected():
    g = TaskGraph()
    with pytest.raises(ValueError):
        g.add_task("a", deps=["a"])


def test_set_status_validates():
    g = _g()
    with pytest.raises(ValueError):
        g.set_status("a", "bogus")
    with pytest.raises(KeyError):
        g.set_status("zzz", "done")


def test_persist_roundtrip(tmp_path):
    g = _g()
    g.set_status("a", "done")
    path = tmp_path / "graph.json"
    g.save(path)
    g2 = TaskGraph.load(path)
    assert g2.tasks["a"]["status"] == "done"
    assert g2.tasks["d"]["deps"] == ["b", "c"]
    assert g2.ready() == ["b", "c"]


def test_load_missing_is_empty(tmp_path):
    assert TaskGraph.load(tmp_path / "nope.json").tasks == {}


# ---- critical path ----

def test_critical_path_linear_chain():
    g = TaskGraph()
    g.add_task("a")
    g.add_task("b", deps=["a"])
    g.add_task("c", deps=["b"])
    path, length = g.critical_path()
    assert path == ["a", "b", "c"] and length == 3.0


def test_critical_path_diamond():
    # a -> {b, c} -> d ; longest chain is length 3 (a, b|c, d)
    path, length = _g().critical_path()
    assert length == 3.0
    assert path[0] == "a" and path[-1] == "d" and len(path) == 3


def test_critical_path_weighted():
    g = TaskGraph()
    g.add_task("a")
    g.add_task("b", deps=["a"])   # heavy
    g.add_task("c", deps=["a"])   # light
    path, length = g.critical_path(weights={"a": 1, "b": 5, "c": 2})
    assert path == ["a", "b"] and length == 6.0


def test_critical_path_empty_and_cycle():
    assert TaskGraph().critical_path() == ([], 0.0)
    g = TaskGraph()
    g.add_task("a", deps=["b"])
    g.tasks["b"] = {"title": "", "deps": ["a"], "status": "todo"}  # cycle
    assert g.critical_path() == ([], 0.0)


def test_tool_critical_op(tmp_path, monkeypatch):
    import maverick.task_graph as tg
    monkeypatch.setattr(tg, "_STORE", tmp_path)
    t = tg.task_graph()
    t.fn({"op": "add", "task": "a"})
    t.fn({"op": "add", "task": "b", "deps": ["a"]})
    out = t.fn({"op": "critical"})
    assert "critical path" in out and "a -> b" in out
