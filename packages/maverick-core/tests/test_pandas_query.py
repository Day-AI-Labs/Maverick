"""Regression tests for the pandas_query tool's memory-bounding behavior.

Focus: parquet and non-lines JSON must not materialize an arbitrarily large
file in full before the row cap is applied (audit unit ``pandas_query``).
"""
from __future__ import annotations

import pytest
from maverick.tools import pandas_query as pqmod

pd = pytest.importorskip("pandas")
pq = pytest.importorskip("pyarrow.parquet")


def test_parquet_load_is_row_capped(tmp_path, monkeypatch):
    """Parquet reads must stop at the cap instead of loading the whole file."""
    monkeypatch.setattr(pqmod, "_MAX_LOAD_ROWS", 50)
    path = tmp_path / "big.parquet"
    pd.DataFrame({"a": range(10_000)}).to_parquet(path)

    # Count how many rows pyarrow actually streams in; with a full read this
    # would be all 10_000 rows, defeating the cap.
    real_iter_batches = pq.ParquetFile.iter_batches
    streamed = {"rows": 0}

    def counting_iter_batches(self, *a, **k):
        for b in real_iter_batches(self, *a, **k):
            streamed["rows"] += b.num_rows
            yield b

    monkeypatch.setattr(pq.ParquetFile, "iter_batches", counting_iter_batches)

    df = pqmod._load(path)

    cap = pqmod._MAX_LOAD_ROWS + 1
    assert len(df) == cap
    # The fix must route through the streaming batch reader (a full
    # ``read_parquet().head()`` would never touch iter_batches, leaving this 0)
    # and stop early — nowhere near the full 10_000 rows.
    assert 0 < streamed["rows"] < 10_000


def test_json_byte_guard_rejects_oversized_file(tmp_path, monkeypatch):
    """Non-lines .json over the byte limit is refused before any pandas read."""
    monkeypatch.setenv("MAVERICK_PANDAS_MAX_JSON_BYTES", "100")
    path = tmp_path / "big.json"
    pd.DataFrame({"a": range(1000)}).to_json(path)
    assert path.stat().st_size > 100

    with pytest.raises(ValueError, match="read limit"):
        pqmod._load(path)


def test_json_under_limit_still_loads(tmp_path, monkeypatch):
    """A small .json under the byte limit loads normally."""
    monkeypatch.setenv("MAVERICK_PANDAS_MAX_JSON_BYTES", str(10 * 1024 * 1024))
    path = tmp_path / "small.json"
    pd.DataFrame({"a": [1, 2, 3]}).to_json(path)
    df = pqmod._load(path)
    assert len(df) == 3
