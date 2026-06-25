"""SIEM forwarder (#56): push rendered audit lines to tcp/udp/http collectors."""
from __future__ import annotations

import socket
import threading

import pytest
from maverick.audit import forwarder


def test_parse_dest_schemes():
    assert forwarder.parse_dest("tcp://h:514") == ("tcp", "h", 514, "")
    assert forwarder.parse_dest("udp://h:514") == ("udp", "h", 514, "")
    s, h, p, url = forwarder.parse_dest("https://siem.example/services/collector/raw")
    assert (s, h, p) == ("https", "siem.example", 443)
    assert url == "https://siem.example/services/collector/raw"
    assert forwarder.parse_dest("http://h/path")[2] == 80  # default port


@pytest.mark.parametrize("bad", [
    "ftp://h:1", "tcp://h", "udp://nohost", "https://", "not-a-uri",
])
def test_parse_dest_rejects_bad(bad):
    with pytest.raises(ValueError):
        forwarder.parse_dest(bad)


def test_forward_tcp_delivers_newline_framed_lines():
    received: list[bytes] = []
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def _accept():
        conn, _ = srv.accept()
        with conn:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                received.append(chunk)

    t = threading.Thread(target=_accept)
    t.start()
    n = forwarder.forward(["a", "b", "c"], f"tcp://127.0.0.1:{port}")
    t.join(timeout=5)
    srv.close()
    assert n == 3
    assert b"".join(received) == b"a\nb\nc\n"


def test_forward_udp_one_datagram_per_event():
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(5)
    port = srv.getsockname()[1]

    n = forwarder.forward(["x", "y"], f"udp://127.0.0.1:{port}")
    assert n == 2
    got = {srv.recvfrom(1024)[0] for _ in range(2)}
    srv.close()
    assert got == {b"x\n", b"y\n"}


def test_forward_http_posts_batch_with_token(monkeypatch):
    captured = {}

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = req.data
        captured["auth"] = req.get_header("Authorization")
        return _Resp()

    monkeypatch.setenv("MAVERICK_SIEM_TOKEN", "hec-token")
    monkeypatch.delenv("MAVERICK_SECRETS_BACKEND", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    n = forwarder.forward(["e1", "e2"], "https://siem.example/raw")
    assert n == 2
    assert captured["body"] == b"e1\ne2\n"
    assert captured["auth"] == "Bearer hec-token"
    assert captured["url"] == "https://siem.example/raw"


def test_forward_http_raises_on_5xx(monkeypatch):
    class _Resp:
        status = 503
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Resp())
    with pytest.raises(RuntimeError, match="503"):
        forwarder.forward(["e1"], "https://siem.example/raw")


def test_forward_http_empty_batch_sends_nothing(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover -- must not be called
        raise AssertionError("urlopen called for empty batch")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert forwarder.forward([], "https://siem.example/raw") == 0
