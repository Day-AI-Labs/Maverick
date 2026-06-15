"""Chat composer file uploads flow into a goal's attachments."""
from __future__ import annotations

from fastapi.testclient import TestClient

_ORIGIN = {"origin": "http://testserver"}


def _client():
    from maverick_dashboard.app import app
    return TestClient(app, headers={"Origin": "http://testserver"})


def _prep(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")  # a provider is configured
    # Keep attachment bytes + the goal run inside the test sandbox.
    import maverick.attachments as att
    monkeypatch.setattr(att, "DEFAULT_ROOT", tmp_path / "attachments")
    monkeypatch.setattr("maverick.runner.run_goal_in_thread", lambda *a, **k: None)
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()


def test_chat_send_stores_attachment(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    r = _client().post(
        "/chat/send",
        data={"title": "summarize this", "description": ""},
        files={"files": ("notes.txt", b"hello world", "text/plain")},
        headers=_ORIGIN, follow_redirects=False,
    )
    assert r.status_code == 303
    from maverick_dashboard import app as dash
    g = dash._world().list_goals()[-1]
    atts = dash._world().list_attachments(g.id)
    assert [a.filename for a in atts] == ["notes.txt"]
    assert atts[0].size_bytes == len(b"hello world")


def test_chat_send_empty_file_input_still_works(monkeypatch, tmp_path):
    """An unfilled file input posts an empty part (filename="") — this must not
    400 a normal, attachment-less goal. Posts the exact multipart a browser sends."""
    _prep(monkeypatch, tmp_path)
    b = "X7X7boundary"
    body = (
        f'--{b}\r\nContent-Disposition: form-data; name="title"\r\n\r\nno file here\r\n'
        f'--{b}\r\nContent-Disposition: form-data; name="files"; filename=""\r\n'
        f'Content-Type: application/octet-stream\r\n\r\n\r\n'
        f'--{b}--\r\n'
    ).encode()
    r = _client().post(
        "/chat/send", content=body, follow_redirects=False,
        headers={"origin": "http://testserver",
                 "content-type": f"multipart/form-data; boundary={b}"},
    )
    assert r.status_code == 303
    from maverick_dashboard import app as dash
    g = dash._world().list_goals()[-1]
    assert dash._world().list_attachments(g.id) == []


def test_chat_send_rejects_disallowed_type(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    r = _client().post(
        "/chat/send",
        data={"title": "bad upload", "description": ""},
        files={"files": ("evil.exe", b"MZ\x90\x00", "application/x-msdownload")},
        headers=_ORIGIN, follow_redirects=False,
    )
    assert r.status_code == 400
    assert "Attachment" in r.json()["detail"]


def test_chat_send_rejects_oversized_upload_without_goal(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    import maverick.attachments as att
    monkeypatch.setattr(att, "MAX_FILE_BYTES", 4)

    r = _client().post(
        "/chat/send",
        data={"title": "too large", "description": ""},
        files={"files": ("notes.txt", b"12345", "text/plain")},
        headers=_ORIGIN, follow_redirects=False,
    )

    assert r.status_code == 400
    assert "file too large" in r.json()["detail"]
    from maverick_dashboard import app as dash
    assert dash._world().list_goals() == []


def test_chat_send_rejects_disallowed_type_without_goal(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    r = _client().post(
        "/chat/send",
        data={"title": "bad upload", "description": ""},
        files={"files": ("evil.exe", b"MZ\x90\x00", "application/x-msdownload")},
        headers=_ORIGIN, follow_redirects=False,
    )

    assert r.status_code == 400
    assert "Attachment" in r.json()["detail"]
    from maverick_dashboard import app as dash
    assert dash._world().list_goals() == []


def test_chat_page_has_attach_control(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    r = _client().get("/chat")
    assert r.status_code == 200
    assert 'name="files"' in r.text
    assert 'id="attach-btn"' in r.text
    assert 'enctype="multipart/form-data"' in r.text
