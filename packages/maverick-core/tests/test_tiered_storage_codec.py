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


def test_read_cold_dedups_duplicate_rows(tmp_path, monkeypatch):
    """Crash-recovery idempotency: archive() durably renames a cold file BEFORE
    its DELETE commits, so a crash in between leaves the same rows in a SECOND
    cold file on the next run. read_cold must yield each id once, not twice.
    """
    monkeypatch.setenv("MAVERICK_WORLD_COLD_CODEC", "gzip")  # dep-free codec
    rows = [{"id": 1, "ts": 10, "v": "a"}, {"id": 2, "ts": 20, "v": "b"}]
    p1 = ts._write_cold_file(tmp_path, "episodes", "ts", rows)
    p2 = ts._write_cold_file(tmp_path, "episodes", "ts", rows)  # the duplicate
    assert p1 != p2
    got = [r["id"] for r in ts.read_cold(tmp_path, "episodes")]
    assert got == [1, 2], f"expected each id once, got {got}"


def test_write_cold_file_concurrent_same_range_no_clobber(tmp_path, monkeypatch):
    """Two processes archiving the SAME date-range must not clobber each other.

    The old `while path.exists()` + os.replace was a TOCTOU: both archivers saw
    the same `-N` free and replaced onto it, destroying one cold file after its
    SQLite rows were already deleted. Each concurrent writer must end up with its
    own distinct, fully-readable file; no rows go missing.
    """
    import threading

    monkeypatch.setenv("MAVERICK_WORLD_COLD_CODEC", "gzip")  # dep-free codec
    monkeypatch.setattr(ts, "_have_pyarrow", lambda: False)
    n = 16
    rows = [{"id": 1, "ts": 10, "v": "a"}, {"id": 2, "ts": 20, "v": "b"}]
    paths: list = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker():
        try:
            p = ts._write_cold_file(tmp_path, "episodes", "ts", rows)
        except (OSError, ValueError) as e:
            with lock:
                errors.append(e)
            return
        with lock:
            paths.append(p)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors[:3]
    # Every writer got a DISTINCT name (no clobber) and every file is on disk.
    assert len(paths) == n
    assert len({p.name for p in paths}) == n, "two writers shared a name"
    for p in paths:
        assert p.exists()
    # No stray temp files survive a successful publish.
    assert not list(tmp_path.glob("*.tmp"))
    # Each file is independently readable (none was left half-written/empty).
    for p in paths:
        assert sorted(r["id"] for r in ts._read_jsonl_gz(p)) == [1, 2]
