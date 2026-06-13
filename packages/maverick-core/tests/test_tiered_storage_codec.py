"""Cold-archive codec selection + zstd round-trip for tiered_storage.

zstd is the [zstd] extra; the round-trip tests importorskip it. Codec
*selection* is tested without the dep via monkeypatched probes.
"""
from __future__ import annotations

import pytest
from maverick import tiered_storage as ts


@pytest.fixture(autouse=True)
def _no_disk_config(monkeypatch):
    # Don't let a real ~/.maverick/config.toml set cold_codec under the tests.
    monkeypatch.setattr(ts, "_world_cfg", dict)
    monkeypatch.delenv("MAVERICK_WORLD_COLD_CODEC", raising=False)


def test_cold_codec_default_auto():
    assert ts._cold_codec() == "auto"


def test_cold_codec_env_wins(monkeypatch):
    monkeypatch.setenv("MAVERICK_WORLD_COLD_CODEC", "zstd")
    assert ts._cold_codec() == "zstd"
    monkeypatch.setenv("MAVERICK_WORLD_COLD_CODEC", "bogus")
    assert ts._cold_codec() == "auto"  # unknown -> auto


def test_cold_codec_from_config(monkeypatch):
    monkeypatch.setattr(ts, "_world_cfg", lambda: {"cold_codec": "gzip"})
    assert ts._cold_codec() == "gzip"


def test_choose_format_auto_gzip_without_pyarrow(monkeypatch):
    monkeypatch.setattr(ts, "_have_pyarrow", lambda: False)
    ext, writer = ts._choose_format("auto")
    assert ext == ".jsonl.gz" and writer is ts._write_jsonl_gz


def test_choose_format_auto_parquet_with_pyarrow(monkeypatch):
    monkeypatch.setattr(ts, "_have_pyarrow", lambda: True)
    ext, writer = ts._choose_format("auto")
    assert ext == ".parquet" and writer is ts._write_parquet


def test_choose_format_gzip_forced_even_with_pyarrow(monkeypatch):
    monkeypatch.setattr(ts, "_have_pyarrow", lambda: True)
    ext, _ = ts._choose_format("gzip")
    assert ext == ".jsonl.gz"


def test_choose_format_zstd_falls_back_to_gzip_when_unavailable(monkeypatch):
    monkeypatch.setattr(ts, "_have_zstd", lambda: False)
    ext, writer = ts._choose_format("zstd")
    assert ext == ".jsonl.gz" and writer is ts._write_jsonl_gz


def test_choose_format_zstd_when_available(monkeypatch):
    monkeypatch.setattr(ts, "_have_zstd", lambda: True)
    monkeypatch.setattr(ts, "_have_pyarrow", lambda: True)  # parquet must NOT win
    ext, writer = ts._choose_format("zstd")
    assert ext == ".jsonl.zst" and writer is ts._write_jsonl_zst


_ROWS = [
    {"id": 1, "ended_at": 1_700_000_000.0, "summary": "alpha"},
    {"id": 2, "ended_at": 1_700_000_100.0, "summary": "bravo"},
]


def test_zstd_roundtrip(tmp_path):
    pytest.importorskip("zstandard")
    path = tmp_path / "episodes-20231114-20231114.jsonl.zst"
    ts._write_jsonl_zst(_ROWS, path)
    assert path.exists()
    back = list(ts._read_jsonl_zst(path))
    assert back == _ROWS


def test_write_cold_file_zstd_and_read_back(tmp_path, monkeypatch):
    pytest.importorskip("zstandard")
    monkeypatch.setenv("MAVERICK_WORLD_COLD_CODEC", "zstd")
    path = ts._write_cold_file(tmp_path, "episodes", "ended_at", _ROWS)
    assert path.name.endswith(".jsonl.zst")
    assert oct(path.stat().st_mode)[-3:] == "600"
    back = list(ts.read_cold(tmp_path, "episodes"))
    assert back == _ROWS


def test_read_cold_mixed_dir(tmp_path, monkeypatch):
    """gzip + zstd files in one dir read fine (codec changed between runs)."""
    pytest.importorskip("zstandard")
    ts._write_jsonl_gz([_ROWS[0]], tmp_path / "episodes-20231114-20231114.jsonl.gz")
    ts._write_jsonl_zst([_ROWS[1]], tmp_path / "episodes-20231114-20231114-2.jsonl.zst")
    back = list(ts.read_cold(tmp_path, "episodes"))
    assert {r["id"] for r in back} == {1, 2}


def test_read_jsonl_zst_clear_error_without_dep(tmp_path, monkeypatch):
    # A .jsonl.zst file present but zstandard not importable -> clear RuntimeError.
    bad = tmp_path / "episodes-x.jsonl.zst"
    bad.write_bytes(b"not really zstd")
    real_import = ts.importlib.import_module

    def _no_zstd(name, *a, **k):
        if name == "zstandard":
            raise ImportError("simulated missing zstandard")
        return real_import(name, *a, **k)

    monkeypatch.setattr(ts.importlib, "import_module", _no_zstd)
    with pytest.raises(RuntimeError, match="zstandard is not importable"):
        list(ts.read_cold(tmp_path, "episodes"))


def test_write_cold_file_auto_unchanged(tmp_path, monkeypatch):
    # Default (auto) without pyarrow stays gzip JSONL -- behavior unchanged.
    monkeypatch.setattr(ts, "_have_pyarrow", lambda: False)
    path = ts._write_cold_file(tmp_path, "episodes", "ended_at", _ROWS)
    assert path.name.endswith(".jsonl.gz")
    back = list(ts.read_cold(tmp_path, "episodes"))
    assert back == _ROWS
