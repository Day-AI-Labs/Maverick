"""Sanctions / watchlist screening — gate every payment + vendor-onboarding path.

A name (payee, vendor, counterparty) is screened against a sanctions list (OFAC
SDN, or any newline/JSON name list the operator supplies) before money moves or a
vendor is onboarded (finance-agent-suite §2.6). Read-only and deterministic: the
matcher normalises names and scores exact + token-overlap matches, so it's a pure,
unit-tested function; the tool loads the list from ``[screening] sdn_path`` (or
``~/.maverick/screening/sdn.txt``) and returns hits for a human to clear.

A hit does **not** auto-block in code — it raises a finding the payment/vendor
flow routes to a human (an OFAC determination is a human act). This is intentional
defence-in-depth, not a substitute for a licensed screening provider (no DOB /
address / fuzzy-alias resolution here — see the honest caveats in the proposal).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import Tool

_DEFAULT_LIST = Path.home() / ".maverick" / "screening" / "sdn.txt"
_PUNCT = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")


def normalize(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for stable comparison."""
    s = _PUNCT.sub(" ", (name or "").lower())
    return _WS.sub(" ", s).strip()


def _tokens(name: str) -> set[str]:
    return {t for t in normalize(name).split() if len(t) > 1}


def _score(query: str, candidate: str) -> float:
    """0–1 match score: 1.0 exact (normalised), else token Jaccard."""
    nq, nc = normalize(query), normalize(candidate)
    if not nq or not nc:
        return 0.0
    if nq == nc:
        return 1.0
    tq, tc = _tokens(query), _tokens(candidate)
    if not tq or not tc:
        return 0.0
    inter = len(tq & tc)
    return inter / len(tq | tc)


def screen(name: str, sdn_names, *, threshold: float = 0.85) -> dict:
    """Screen ``name`` against ``sdn_names``; return ``{match, hits, screened}``.

    ``hits`` are ``{name, score}`` at or above ``threshold``, highest first.
    """
    hits = []
    for cand in sdn_names or []:
        s = _score(name, str(cand))
        if s >= threshold:
            hits.append({"name": str(cand), "score": round(s, 3)})
    hits.sort(key=lambda h: -h["score"])
    return {"match": bool(hits), "hits": hits, "screened": str(name)}


def load_list(path: str | Path) -> list[str]:
    """Load names from a newline list or a JSON array / ``{"names": [...]}``."""
    p = Path(path)
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            return [str(x) for x in data]
        if isinstance(data, dict) and isinstance(data.get("names"), list):
            return [str(x) for x in data["names"]]
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _list_path() -> Path:
    try:
        from ..config import load_config
        cfg = (load_config() or {}).get("screening") or {}
        sp = str(cfg.get("sdn_path") or "").strip()
        if sp:
            return Path(sp).expanduser()
    except Exception:  # pragma: no cover -- config never blocks screening
        pass
    return _DEFAULT_LIST


_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["check"], "default": "check"},
        "name": {"type": "string", "description": "the payee / vendor / counterparty to screen"},
        "threshold": {"type": "number", "description": "match threshold 0–1 (default 0.85)"},
    },
    "required": ["name"],
}


def _run(args: dict[str, Any]) -> str:
    name = (args.get("name") or "").strip()
    if not name:
        return "ERROR: name is required"
    path = _list_path()
    sdn = load_list(path)
    if not sdn:
        return (f"ERROR: no sanctions list found at {path}. Set [screening] "
                "sdn_path to an OFAC SDN export (newline or JSON name list).")
    threshold = float(args.get("threshold") or 0.85)
    result = screen(name, sdn, threshold=threshold)
    if not result["match"]:
        return f"CLEAR: {name!r} not found on the sanctions list ({len(sdn)} names)."
    lines = [f"POSSIBLE SANCTIONS HIT for {name!r} — route to a human for an OFAC "
             "determination (do not proceed):"]
    lines += [f"  - {h['name']} (score {h['score']})" for h in result["hits"][:10]]
    return "\n".join(lines)


def sanctions_screen() -> Tool:
    return Tool(
        name="screen_sanctions",
        description=(
            "Screen a payee / vendor / counterparty name against a sanctions list "
            "(OFAC SDN or operator-supplied). op: check (name, threshold). Returns "
            "CLEAR or possible hits for a human to clear — never auto-proceeds on a "
            "hit. List path: [screening] sdn_path."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )


__all__ = ["normalize", "screen", "load_list", "sanctions_screen"]
