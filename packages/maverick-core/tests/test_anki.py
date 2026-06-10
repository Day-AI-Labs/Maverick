"""Anki (AnkiConnect) connector: RPC shaping, confirm gates, error hints."""
from __future__ import annotations

import sys
import types

from maverick.tools.anki import anki


def _fake_httpx(monkeypatch, handler):
    calls = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    def post(url, json=None, timeout=None):
        calls.append((url, json))
        return _Resp(handler(json))

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(post=post))
    return calls


def test_decks(monkeypatch):
    _fake_httpx(monkeypatch, lambda req: {"result": ["Spanish", "Algorithms"], "error": None})
    out = anki().fn({"op": "decks"})
    assert out == "Algorithms\nSpanish"


def test_add_note_requires_confirm(monkeypatch):
    calls = _fake_httpx(monkeypatch, lambda req: {"result": 123, "error": None})
    t = anki()
    dry = t.fn({"op": "add_note", "deck": "Spanish", "front": "hola", "back": "hello"})
    assert dry.startswith("DRY RUN") and not calls
    # Stringy confirm fails closed (as_bool).
    dry2 = t.fn({"op": "add_note", "deck": "S", "front": "f", "back": "b",
                 "confirm": "true"})
    assert dry2.startswith("DRY RUN") and not calls


def test_add_note_confirmed(monkeypatch):
    calls = _fake_httpx(monkeypatch, lambda req: {"result": 1501, "error": None})
    out = anki().fn({"op": "add_note", "deck": "Spanish", "front": "hola",
                     "back": "hello", "tags": ["maverick"], "confirm": True})
    assert out == "added note 1501 to 'Spanish'"
    url, payload = calls[0]
    assert url == "http://127.0.0.1:8765"
    note = payload["params"]["note"]
    assert note["fields"] == {"Front": "hola", "Back": "hello"}
    assert note["options"]["allowDuplicate"] is False
    assert payload["version"] == 6


def test_find_two_phase(monkeypatch):
    def handler(req):
        if req["action"] == "findNotes":
            return {"result": [1, 2], "error": None}
        return {"result": [
            {"noteId": 1, "fields": {"Front": {"value": "hola"}}},
            {"noteId": 2, "fields": {"Front": {"value": "adios"}}},
        ], "error": None}

    _fake_httpx(monkeypatch, handler)
    out = anki().fn({"op": "find", "query": "deck:Spanish"})
    assert "[1] hola" in out and "[2] adios" in out
    assert anki().fn({"op": "find"}).startswith("ERROR")


def test_anki_error_surfaces(monkeypatch):
    _fake_httpx(monkeypatch, lambda req: {"result": None, "error": "deck not found"})
    out = anki().fn({"op": "add_note", "deck": "X", "front": "f", "back": "b",
                     "confirm": True})
    assert out == "ERROR: deck not found"


def test_unreachable_hint(monkeypatch):
    class _Boom:
        @staticmethod
        def post(url, json=None, timeout=None):
            raise ConnectionError("connection refused")

    monkeypatch.setitem(sys.modules, "httpx", _Boom)
    out = anki().fn({"op": "decks"})
    assert "cannot reach AnkiConnect" in out and "add-on" in out


def test_sync_gated_and_validation(monkeypatch):
    _fake_httpx(monkeypatch, lambda req: {"result": None, "error": None})
    t = anki()
    assert t.fn({"op": "sync"}).startswith("DRY RUN")
    assert t.fn({"op": "sync", "confirm": True}) == "sync triggered"
    assert t.fn({"op": "add_note", "deck": "d"}).startswith("ERROR")
    assert t.fn({"op": "bogus"}).startswith("ERROR")


def test_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        pass

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    assert "anki" in names
