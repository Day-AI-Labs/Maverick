"""Spreadsheet tool: CSV (stdlib) + XLSX (openpyxl extra) (ROADMAP 2027 H1)."""
from __future__ import annotations

import json

import pytest
from maverick.tools import spreadsheet as ss

# ---- CSV (stdlib, always available) -----------------------------------------

def test_csv_write_read_info(tmp_path):
    p = tmp_path / "data.csv"
    assert ss._run({"op": "write", "path": str(p),
                    "rows": [["a", "b"], [1, 2], [3, 4]]}).startswith("wrote 3")
    rows = json.loads(ss._run({"op": "read", "path": str(p)}))
    assert rows[0] == ["a", "b"] and rows[1] == ["1", "2"]   # csv reads back as strings
    assert "rows=3" in ss._run({"op": "info", "path": str(p)})


def test_set_cell_rejects_csv(tmp_path):
    p = tmp_path / "data.csv"
    ss._run({"op": "write", "path": str(p), "rows": [["x"]]})
    assert "xlsx-only" in ss._run({"op": "set_cell", "path": str(p), "cell": "A1", "value": 1})


def test_errors():
    assert ss._run({"op": "read"}).startswith("ERROR: path is required")
    assert ss._run({"op": "", "path": "x"}).startswith("ERROR: op is required")
    assert ss._run({"op": "read", "path": "/nope/missing.csv"}).startswith("ERROR: no such file")
    assert ss._run({"op": "bogus", "path": "x.csv"}).startswith("ERROR")


# ---- XLSX (needs openpyxl) --------------------------------------------------

def test_xlsx_write_read_setcell_info(tmp_path):
    pytest.importorskip("openpyxl")
    p = tmp_path / "book.xlsx"
    assert ss._run({"op": "write", "path": str(p),
                    "rows": [["h1", "h2"], [10, 20]], "sheet": "Data"}).startswith("wrote 2")
    rows = json.loads(ss._run({"op": "read", "path": str(p), "sheet": "Data"}))
    assert rows[0] == ["h1", "h2"] and rows[1] == [10, 20]   # xlsx preserves int types
    assert ss._run({"op": "set_cell", "path": str(p), "cell": "A3",
                    "value": 99, "sheet": "Data"}).startswith("set A3")
    rows2 = json.loads(ss._run({"op": "read", "path": str(p), "sheet": "Data"}))
    assert rows2[2][0] == 99
    assert "xlsx sheets" in ss._run({"op": "info", "path": str(p)})


def test_xlsx_graceful_without_openpyxl(tmp_path, monkeypatch):
    # If openpyxl is unavailable, xlsx ops fail with an actionable install hint
    # rather than a raw ImportError.
    def _boom():
        raise RuntimeError("openpyxl not installed; .xlsx support needs it. "
                           "Run: pip install 'maverick-agent[spreadsheet]'")
    monkeypatch.setattr(ss, "_openpyxl", _boom)
    out = ss._run({"op": "write", "path": str(tmp_path / "x.xlsx"), "rows": [["a"]]})
    assert out.startswith("ERROR") and "maverick-agent[spreadsheet]" in out


def test_factory_shape():
    t = ss.spreadsheet()
    assert t.name == "spreadsheet" and t.fn is ss._run
