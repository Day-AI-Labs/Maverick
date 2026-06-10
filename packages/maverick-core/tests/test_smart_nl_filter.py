"""smart_nl_filter: NL-to-predicate parsing and row filtering."""
from __future__ import annotations

import json

from maverick.tools.smart_nl_filter import smart_nl_filter


def _parse(query):
    return smart_nl_filter().fn({"op": "parse", "query": query})


def _predicate(query):
    out = _parse(query)
    assert out.startswith("PREDICATE: ")
    return json.loads(out[len("PREDICATE: "):])


def _apply(rows, predicate):
    out = smart_nl_filter().fn({"op": "apply", "rows": rows, "predicate": predicate})
    assert out.startswith("MATCHED")
    return json.loads(out.split("\n", 1)[1])


def test_parse_and_connector():
    p = _predicate("cost > 5 and tool = shell")
    assert p["connector"] == "AND"
    assert p["clauses"] == [
        {"field": "cost", "op": ">", "value": 5},
        {"field": "tool", "op": "=", "value": "shell"},
    ]


def test_parse_or_and_operators():
    p = _predicate("status != ok or cost >= 100")
    assert p["connector"] == "OR"
    assert p["clauses"][0] == {"field": "status", "op": "!=", "value": "ok"}
    assert p["clauses"][1] == {"field": "cost", "op": ">=", "value": 100}


def test_parse_shorthands():
    failed = _predicate("failed runs")
    assert failed["clauses"] == [{"field": "status", "op": "=", "value": "failed"}]
    recent = _predicate("last 7 days")
    assert recent["clauses"] == [{"field": "age_days", "op": "<=", "value": 7}]


def test_apply_and_filtering():
    rows = [
        {"cost": 10, "tool": "shell"},
        {"cost": 2, "tool": "shell"},
        {"cost": 10, "tool": "browser"},
    ]
    kept = _apply(rows, "cost > 5 and tool = shell")
    assert kept == [{"cost": 10, "tool": "shell"}]


def test_apply_or_and_contains():
    rows = [
        {"name": "deploy prod", "cost": 1},
        {"name": "run tests", "cost": 50},
        {"name": "idle", "cost": 1},
    ]
    kept = _apply(rows, "name contains prod or cost > 40")
    names = sorted(r["name"] for r in kept)
    assert names == ["deploy prod", "run tests"]


def test_errors_mixed_connector_and_bad_clause():
    assert _parse("a > 1 and b = 2 or c = 3").startswith("ERROR")
    assert _parse("not a real filter").startswith("ERROR")
    assert smart_nl_filter().fn({"op": "parse"}).startswith("ERROR")
    assert smart_nl_filter().fn({"op": "nope"}).startswith("ERROR")


def test_factory_shape():
    t = smart_nl_filter()
    assert t.name == "smart_nl_filter"
    assert t.parallel_safe is True
