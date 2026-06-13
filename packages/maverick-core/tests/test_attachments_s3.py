"""Tests for the opt-in S3 attachment mirror. boto3 is faked; the local store
remains the source of truth and the mirror is fail-open."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

from maverick import attachments as att


def _fake_boto3(monkeypatch):
    client = MagicMock(name="s3 client")
    boto3 = MagicMock(name="boto3")
    boto3.client.return_value = client
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    return client


def test_mirror_off_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("MAVERICK_ATTACH_S3_BUCKET", raising=False)
    import maverick.config as config_mod
    monkeypatch.setattr(config_mod, "load_config", dict)
    client = _fake_boto3(monkeypatch)
    st = att.store(1, "a.txt", "text/plain", b"hello", root=tmp_path)
    assert st.path.exists()
    assert not client.put_object.called


def test_mirror_uploads_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_ATTACH_S3_BUCKET", "my-bucket")
    monkeypatch.setenv("MAVERICK_ATTACH_S3_PREFIX", "attach")
    client = _fake_boto3(monkeypatch)
    st = att.store(7, "doc.txt", "text/plain", b"world", root=tmp_path)
    assert st.path.exists()  # local copy is still written
    client.put_object.assert_called_once()
    kw = client.put_object.call_args.kwargs
    assert kw["Bucket"] == "my-bucket"
    assert kw["Key"] == f"attach/7/{st.path.name}"
    assert kw["Body"] == b"world"
    assert kw["ContentType"] == "text/plain"


def test_mirror_failure_is_fail_open(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_ATTACH_S3_BUCKET", "b")
    client = _fake_boto3(monkeypatch)
    client.put_object.side_effect = RuntimeError("s3 down")
    st = att.store(2, "a.txt", "text/plain", b"x", root=tmp_path)  # must not raise
    assert st.path.exists()


def test_s3_fetch_pulls_missing_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_ATTACH_S3_BUCKET", "b")
    monkeypatch.delenv("MAVERICK_ATTACH_S3_PREFIX", raising=False)
    client = _fake_boto3(monkeypatch)
    body = MagicMock()
    body.read.return_value = b"bytes-from-s3"
    client.get_object.return_value = {"Body": body}
    p = att.s3_fetch(9, "abcd1234-zz.txt", root=tmp_path)
    assert p is not None and p.read_bytes() == b"bytes-from-s3"
    client.get_object.assert_called_once_with(Bucket="b", Key="9/abcd1234-zz.txt")
    # Second fetch short-circuits on the local file.
    client.get_object.reset_mock()
    assert att.s3_fetch(9, "abcd1234-zz.txt", root=tmp_path) == p
    assert not client.get_object.called


def test_s3_fetch_when_off_or_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("MAVERICK_ATTACH_S3_BUCKET", raising=False)
    import maverick.config as config_mod
    monkeypatch.setattr(config_mod, "load_config", dict)
    assert att.s3_fetch(1, "x.txt", root=tmp_path) is None
    monkeypatch.setenv("MAVERICK_ATTACH_S3_BUCKET", "b")
    client = _fake_boto3(monkeypatch)
    client.get_object.side_effect = RuntimeError("NoSuchKey")
    assert att.s3_fetch(1, "x.txt", root=tmp_path) is None


def test_s3_fetch_rejects_unsafe_names_before_s3(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_ATTACH_S3_BUCKET", "b")
    client = _fake_boto3(monkeypatch)

    for name in ("../config.toml", "/tmp/config.toml", "subdir/file.txt", "bad\x00.txt"):
        try:
            att.s3_fetch(9, name, root=tmp_path)
        except att.AttachmentRejected:
            pass
        else:  # pragma: no cover - keeps the assertion message useful
            raise AssertionError(f"accepted unsafe S3 attachment name {name!r}")

    assert not client.get_object.called
    assert not (tmp_path / "config.toml").exists()


def test_s3_fetch_enforces_file_size_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_ATTACH_S3_BUCKET", "b")
    monkeypatch.setattr(att, "MAX_FILE_BYTES", 4)
    client = _fake_boto3(monkeypatch)
    body = MagicMock()
    body.read.return_value = b"abcde"
    client.get_object.return_value = {"Body": body}

    try:
        att.s3_fetch(9, "abcd1234-zz.txt", root=tmp_path)
    except att.AttachmentRejected:
        pass
    else:  # pragma: no cover - keeps the assertion message useful
        raise AssertionError("accepted oversized S3 attachment")

    body.read.assert_called_once_with(5)
    assert not (tmp_path / "9" / "abcd1234-zz.txt").exists()
