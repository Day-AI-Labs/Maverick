"""Per-user preference notes, distilled by the dreaming loop.

Compaction summarizes WITHIN a conversation; this consolidates ACROSS them:
explicit preference statements a user has made ("I prefer tables", "never
use emoji", "call me Sam") become a short briefing note injected into that
user's future runs, so every conversation stops re-learning the same
preferences.

Extraction is deterministic — a conservative phrase grammar over the user's
own turns, no LLM — so nothing a third party smuggles into tool output can
become a persisted "preference". Notes are scoped to (channel, user_id) and
only ever injected for that same scope; recall sanitizes + Shield-scans the
text and frames it as untrusted data. Produced by ``maverick dream``
(``[dreaming] user_notes``); injection is a no-op when the store is empty.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from .paths import data_dir

log = logging.getLogger(__name__)

DEFAULT_PATH = data_dir("dreams", "user_notes.ndjson")


def default_path() -> Path:
    return _tenant_path("dreams/user_notes.ndjson", DEFAULT_PATH)


def _tenant_path(name: str, legacy):
    """Item-30 isolation: with an ACTIVE tenant, this store lives under the
    tenant's data dir (one tenant's learned memory can never feed another's
    runs); single-tenant resolution keeps the legacy location unchanged."""
    try:
        from .paths import current_tenant, data_dir
        if current_tenant():
            return data_dir(*name.split("/"))
    except Exception:  # pragma: no cover -- isolation never blocks resolution
        pass
    return legacy


# Sentences that are explicit self-reported preferences. Conservative on
# purpose: false negatives just mean we learn less.
_PREF_RE = re.compile(
    r"(?:\bi(?:'d)? prefer\b"
    r"|\bcall me\b"
    r"|\bfrom now on\b"
    r"|\bplease (?:always|never)\b"
    r"|^always\b"
    r"|^never\b"
    r"|\brespond (?:in|with|using)\b"
    r"|\banswer (?:in|with|using)\b)",
    re.IGNORECASE,
)
_SENT_SPLIT = re.compile(r"(?<=[.!?\n])\s+")
_MAX_NOTE_LEN = 160


def extract_preferences(text: str) -> list[str]:
    """Preference sentences in a user message. Pure and deterministic."""
    out: list[str] = []
    for sent in _SENT_SPLIT.split(str(text or "")):
        s = " ".join(sent.split()).strip()
        if not s or len(s) > _MAX_NOTE_LEN:
            continue
        if _PREF_RE.search(s):
            out.append(s)
    return out


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) >= 3}


def _near_dup(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.8


def consolidate(
    world: Any, *, path: Path | str | None = None,
    max_conversations: int = 20, turns_per_conversation: int = 50,
    max_notes_per_user: int = 8, now: float | None = None,
) -> int:
    """Scan recent conversations and (re)write the per-user note store.

    Returns how many notes were written. The store is fully rewritten each
    dream cycle (atomic), so an edited or deleted conversation stops feeding
    notes on the next dream — no stale memory of retracted preferences.
    """
    p = Path(path) if path is not None else default_path()
    ts = now if now is not None else time.time()
    notes: list[dict] = []
    try:
        conversations = world.list_conversations() or []
    except Exception as e:  # pragma: no cover -- notes never block a dream
        log.debug("user_notes: conversation scan failed: %s", e)
        return 0
    conversations = sorted(
        conversations, key=lambda c: getattr(c, "last_seen", 0.0), reverse=True,
    )[:max(1, max_conversations)]
    for conv in conversations:
        channel = getattr(conv, "channel", "") or ""
        user_id = getattr(conv, "user_id", "") or ""
        if not channel or not user_id:
            continue
        per_user = [n["note"] for n in notes
                    if n["channel"] == channel and n["user_id"] == user_id]
        try:
            turns = world.recent_turns(conv.id, limit=turns_per_conversation)
        except Exception:  # pragma: no cover
            continue
        for turn in turns:
            if getattr(turn, "role", "") != "user":
                continue
            for pref in extract_preferences(getattr(turn, "content", "") or ""):
                if len(per_user) >= max_notes_per_user:
                    break
                if any(_near_dup(pref, prior) for prior in per_user):
                    continue
                per_user.append(pref)
                notes.append({
                    "ts": ts, "channel": channel, "user_id": user_id,
                    "note": pref,
                })
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for n in notes:
                f.write(json.dumps(n, default=str) + "\n")
        os.replace(tmp, p)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    except OSError as e:
        log.warning("user_notes: write failed: %s", e)
        return 0
    return len(notes)


def notes_for(
    channel: str | None, user_id: str | None,
    path: Path | str | None = None, *, k: int = 8,
) -> list[str]:
    """The stored notes for exactly this (channel, user_id) scope."""
    if not channel or not user_id:
        return []
    p = Path(path) if path is not None else default_path()
    if not p.exists():
        return []
    out: list[str] = []
    try:
        with open(p, encoding="utf-8") as f:
            for raw in f:
                try:
                    d = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if d.get("channel") == channel and d.get("user_id") == user_id:
                    note = str(d.get("note", "")).strip()
                    if note:
                        out.append(note)
    except OSError:
        return []
    return out[:max(1, k)]


def erase_notes(
    channel: str | None, user_ids: str | list[str] | tuple[str, ...] | set[str],
    path: Path | str | None = None,
) -> int:
    """Remove persisted notes for ``channel`` and the given user id(s).

    Returns the number of scoped note records removed. Malformed lines and
    unrelated scopes are preserved so erasure is narrow and best-effort.
    """
    if not channel:
        return 0
    if isinstance(user_ids, str):
        targets = {user_ids}
    else:
        targets = {str(u) for u in user_ids if u}
    if not targets:
        return 0

    p = Path(path) if path is not None else default_path()
    if not p.exists():
        return 0

    kept: list[str] = []
    removed = 0
    try:
        with open(p, encoding="utf-8") as f:
            for raw in f:
                try:
                    d = json.loads(raw)
                except json.JSONDecodeError:
                    kept.append(raw)
                    continue
                if d.get("channel") == channel and d.get("user_id") in targets:
                    removed += 1
                    continue
                kept.append(raw)
        if removed:
            tmp = p.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(kept)
            os.replace(tmp, p)
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
    except OSError as e:
        log.warning("user_notes: erase failed: %s", e)
        return 0
    return removed


def format_context(notes: list[str], *, shield: Any | None = None) -> str:
    """Render notes as a brief addendum (untrusted, self-reported data)."""
    if not notes:
        return ""
    safe: list[str] = []
    for note in notes:
        text = str(note or "")
        try:
            from .safety.secret_detector import redact as _redact
            text, _ = _redact(text)
        except Exception:  # pragma: no cover
            pass
        if shield is not None:
            try:
                verdict = shield.scan_input(text)
                if not getattr(verdict, "allowed", True):
                    continue
            except Exception:  # pragma: no cover
                pass
        safe.append(text[:_MAX_NOTE_LEN])
    if not safe:
        return ""
    lines = [
        "",
        "## Known preferences for this user (self-reported, untrusted)",
        "",
    ]
    lines += [f"- {s}" for s in safe]
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_PATH",
    "extract_preferences",
    "consolidate",
    "notes_for",
    "erase_notes",
    "format_context",
]
