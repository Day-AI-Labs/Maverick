"""Tests for the second batch of pre-launch hardening fixes."""


def test_spotify_id_rejects_path_traversal():
    from maverick.tools.spotify_tool import _safe_id
    assert _safe_id("3n3Ppam7vgaVa1iaRUc9Lp")  # real Base62 track id shape
    assert not _safe_id("../albums/x")
    assert not _safe_id("a/b")
    assert not _safe_id("a.b")
    assert not _safe_id("")


def _email_creds(monkeypatch):
    monkeypatch.setenv("EMAIL_USER", "me@example.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "pw")


def test_email_fetch_requires_numeric_uid(monkeypatch):
    _email_creds(monkeypatch)
    from maverick.tools.email_tool import _fetch
    assert "numeric uid" in _fetch({"uid": "1 2 OR 1=1"})
    assert "numeric uid" in _fetch({"uid": "../etc"})


def test_email_list_rejects_folder_control_chars(monkeypatch):
    _email_creds(monkeypatch)
    from maverick.tools.email_tool import _list_inbox
    assert "invalid folder" in _list_inbox({"folder": "INBOX\r\nA001 DELETE"})
