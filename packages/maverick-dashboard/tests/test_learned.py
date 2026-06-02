"""Learned-capability ledger panel + generated-tool removal (#427)."""
from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _isolate(monkeypatch, tmp_path):
    """Point the self-learning ledger + generated-tools dir at tmp_path."""
    from maverick import self_learning
    ledger = tmp_path / "learned.ndjson"
    gen = tmp_path / "generated_tools"
    gen.mkdir()
    monkeypatch.setattr(self_learning, "LEARNED_PATH", ledger)
    monkeypatch.setattr(self_learning, "GENERATED_TOOLS_DIR", gen)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    return ledger, gen


def _write_ledger(path, entries):
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


def test_learned_panel_renders_ledger_entries(monkeypatch, tmp_path):
    ledger, _gen = _isolate(monkeypatch, tmp_path)
    _write_ledger(ledger, [
        {"ts": time.time(), "need": "send an sms", "kind": "tool",
         "name": "send_sms", "source": "generated", "outcome": "acquired"},
        {"ts": time.time(), "need": "scrape a page", "kind": "skill",
         "name": "web_scrape", "source": "catalog", "outcome": "failed"},
    ])
    text = _client().get("/learned").text
    assert "learned capabilities" in text.lower()
    assert "send_sms" in text
    assert "web_scrape" in text
    assert "send an sms" in text
    assert "acquired" in text and "failed" in text


def test_learned_page_renders_empty(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    text = _client().get("/learned").text
    assert "Nothing learned yet" in text
    assert "No generated tools" in text
    # Nav link present.
    assert 'href="/learned"' in text


def test_generated_tools_list_renders(monkeypatch, tmp_path):
    _ledger, gen = _isolate(monkeypatch, tmp_path)
    (gen / "send_sms.py").write_text("# tool\n", encoding="utf-8")
    (gen / ".staging_x.py").write_text("# hidden\n", encoding="utf-8")
    text = _client().get("/learned").text
    assert "send_sms.py" in text
    # Dot/underscore-prefixed staging files are not listed.
    assert ".staging_x.py" not in text
    # API shape mirrors the page.
    body = _client().get("/api/v1/learned").json()
    assert "send_sms.py" in body["generated_tools"]


def test_delete_removes_only_named_file(monkeypatch, tmp_path):
    _ledger, gen = _isolate(monkeypatch, tmp_path)
    (gen / "bad.py").write_text("# bad\n", encoding="utf-8")
    (gen / "good.py").write_text("# good\n", encoding="utf-8")
    client = _client()
    r = client.request(
        "DELETE", "/api/v1/generated-tools/bad.py",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 204
    assert not (gen / "bad.py").exists()
    assert (gen / "good.py").exists()


def test_delete_missing_file_404(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    client = _client()
    r = client.request(
        "DELETE", "/api/v1/generated-tools/nope.py",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 404


def test_delete_rejects_traversal(monkeypatch, tmp_path):
    """A traversal / outside-dir name must be refused and touch nothing."""
    _ledger, gen = _isolate(monkeypatch, tmp_path)
    secret = tmp_path / "secret.py"
    secret.write_text("# do not delete\n", encoding="utf-8")
    client = _client()
    # Names that reach the handler are rejected with 400; names whose
    # decoded path contains a separator (../, subdir/) never route to it
    # and 404 — either way the target is refused, never deleted.
    for name in ("foo.txt", "x.py.bak"):
        r = client.request(
            "DELETE", f"/api/v1/generated-tools/{name}",
            headers={"Origin": "http://testserver"},
        )
        assert r.status_code == 400, name
    for name in ("..", "..%2Fsecret.py", "subdir%2Fx.py"):
        r = client.request(
            "DELETE", f"/api/v1/generated-tools/{name}",
            headers={"Origin": "http://testserver"},
        )
        assert r.status_code in (400, 404), name
    # The out-of-dir target survived every attempt.
    assert secret.exists()


def test_delete_respects_same_origin(monkeypatch, tmp_path):
    """Cross-site DELETE (no token, bad Origin) is blocked by middleware."""
    _ledger, gen = _isolate(monkeypatch, tmp_path)
    (gen / "bad.py").write_text("# bad\n", encoding="utf-8")
    client = _client()
    r = client.request(
        "DELETE", "/api/v1/generated-tools/bad.py",
        headers={"Origin": "http://evil.example"},
    )
    assert r.status_code == 403
    # The file survives the blocked request.
    assert (gen / "bad.py").exists()
