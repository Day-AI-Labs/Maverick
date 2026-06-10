"""memory_safe_parse: bounded parsing of untrusted JSON/CSV."""
from __future__ import annotations

from maverick.tools.memory_safe_parse import memory_safe_parse


def _run(**kw):
    return memory_safe_parse().fn({"op": "parse", **kw})


def test_ok_json_shape_summary():
    out = _run(text='{"a": 1, "b": [1, 2, 3]}', format="json")
    assert out.startswith("OK json")
    assert "dict" in out


def test_reject_oversize():
    out = _run(text="x" * 100, format="csv", max_bytes=10)
    assert out.startswith("REJECT") and "max_bytes" in out


def test_reject_too_deep():
    deep = "[" * 50 + "]" * 50
    out = _run(text=deep, format="json", max_depth=5)
    assert out.startswith("REJECT") and "max_depth" in out


def test_reject_too_many_items():
    out = _run(text="[" + ",".join("1" for _ in range(20)) + "]",
               format="json", max_items=5)
    assert out.startswith("REJECT") and "max_items" in out


def test_invalid_json_does_not_raise():
    out = _run(text="{not valid", format="json")
    assert out.startswith("REJECT") and "invalid JSON" in out


def test_csv_rows_and_header_cols():
    out = _run(text="a,b,c\n1,2,3\n4,5,6", format="csv")
    assert out.startswith("OK csv")
    assert "3 row(s)" in out and "3 column(s)" in out


def test_errors_and_contract():
    assert memory_safe_parse().fn({"op": "parse", "text": 123}).startswith("ERROR")
    assert _run(text="{}", format="xml").startswith("ERROR")
    t = memory_safe_parse()
    assert t.name == "memory_safe_parse" and t.parallel_safe is True
