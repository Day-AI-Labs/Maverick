"""Anki integration via AnkiConnect (roadmap: 2027 H2 ecosystem).

Spaced repetition is the natural sink for what an agent researches: turn
findings into flashcards. This speaks **AnkiConnect** — the de-facto local
REST API the Anki add-on exposes on ``127.0.0.1:8765`` — so cards land in
the user's own collection, no cloud service involved.

Local-only by default: the base URL must stay loopback unless the operator
explicitly overrides ``MAVERICK_ANKI_URL`` (AnkiConnect has no auth; pointing
an agent at a remote instance is an operator decision, not a model's).

ops:
  - decks()                              — list deck names.
  - models()                             — list note types.
  - add_note(deck, front, back[, model, tags, confirm])
      — create a Basic note (writes the collection: confirm=true required).
  - find(query[, limit])                 — search notes (Anki query syntax).
  - sync(confirm)                        — trigger an AnkiWeb sync.
"""
from __future__ import annotations

import os
from typing import Any

from . import Tool, as_bool

DEFAULT_URL = "http://127.0.0.1:8765"
_API_VERSION = 6


def _base_url() -> str:
    return os.environ.get("MAVERICK_ANKI_URL", "").strip() or DEFAULT_URL


def _call(action: str, **params: Any) -> Any:
    """One AnkiConnect RPC: {action, version, params} -> result | raise."""
    import httpx
    r = httpx.post(_base_url(), json={
        "action": action, "version": _API_VERSION,
        **({"params": params} if params else {}),
    }, timeout=15)
    r.raise_for_status()
    payload = r.json()
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    return payload.get("result")


def _run(args: dict[str, Any]) -> str:  # noqa: C901 -- flat op dispatch
    op = args.get("op")
    try:
        if op == "decks":
            decks = _call("deckNames") or []
            return "\n".join(sorted(decks)) or "(no decks)"

        if op == "models":
            models = _call("modelNames") or []
            return "\n".join(sorted(models)) or "(no note types)"

        if op == "find":
            query = str(args.get("query") or "").strip()
            if not query:
                return "ERROR: query is required (Anki search syntax, e.g. 'deck:Spanish')"
            limit = max(1, min(int(args.get("limit") or 20), 100))
            ids = (_call("findNotes", query=query) or [])[:limit]
            if not ids:
                return "(no matching notes)"
            infos = _call("notesInfo", notes=ids) or []
            lines = []
            for n in infos:
                fields = n.get("fields") or {}
                front = (fields.get("Front") or {}).get("value", "")
                lines.append(f"[{n.get('noteId')}] {front[:120]}")
            return "\n".join(lines)

        if op == "add_note":
            deck = str(args.get("deck") or "").strip()
            front = str(args.get("front") or "").strip()
            back = str(args.get("back") or "").strip()
            if not (deck and front and back):
                return "ERROR: deck, front, and back are required"
            if not as_bool(args.get("confirm")):
                return (f"DRY RUN: would add to deck {deck!r}: "
                        f"Front={front[:80]!r} Back={back[:80]!r}. "
                        "Pass confirm=true to write the note.")
            note = {
                "deckName": deck,
                "modelName": str(args.get("model") or "Basic"),
                "fields": {"Front": front, "Back": back},
                "tags": [str(t) for t in (args.get("tags") or [])],
                "options": {"allowDuplicate": False},
            }
            note_id = _call("addNote", note=note)
            return f"added note {note_id} to {deck!r}"

        if op == "sync":
            if not as_bool(args.get("confirm")):
                return "DRY RUN: pass confirm=true to trigger an AnkiWeb sync."
            _call("sync")
            return "sync triggered"

        return f"ERROR: unknown op {op!r}"
    except Exception as e:
        if "Connect" in type(e).__name__ or "connect" in str(e).lower():
            return (f"ERROR: cannot reach AnkiConnect at {_base_url()} — is Anki "
                    "running with the AnkiConnect add-on (code 2055492159)?")
        return f"ERROR: {e}"


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["decks", "models", "find", "add_note", "sync"]},
        "deck": {"type": "string"},
        "front": {"type": "string"},
        "back": {"type": "string"},
        "model": {"type": "string", "description": "note type (default Basic)"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "query": {"type": "string", "description": "Anki search syntax (find)"},
        "limit": {"type": "integer"},
        "confirm": {"type": "boolean", "description": "required true for add_note/sync"},
    },
    "required": ["op"],
}


def anki() -> Tool:
    return Tool(
        name="anki",
        description=(
            "Anki flashcards via the local AnkiConnect add-on "
            "(127.0.0.1:8765). ops: decks, models, find (Anki query syntax), "
            "add_note (deck/front/back, confirm=true required), sync "
            "(confirm=true). Turn research findings into spaced-repetition "
            "cards in the user's own collection."
        ),
        input_schema=_SCHEMA,
        fn=_run,
    )
