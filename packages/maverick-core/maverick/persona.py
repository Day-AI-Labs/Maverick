"""Configurable agent persona.

The persona is a thin layer that customizes the agent's voice without
changing its capabilities or safety surface. Read from [persona] in
``~/.maverick/config.toml``::

    [persona]
    name = "Atlas"
    style = "concise"   # concise | thorough | friendly | formal | playful
    addendum = "Always cite sources with URLs."

All three keys are optional. Empty persona = generic assistant
(unchanged from pre-persona behavior).

The persona block is appended to every agent's system prompt by
``agent.py``. It does NOT alter the orchestrator's playbook, tool
access, or safety scans -- it's purely a voice / tone customization.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Unknown [persona] style values we've already warned about, so a misconfigured
# style logs once per process rather than on every agent build.
_warned_styles: set[str] = set()

STYLES = {
    "concise":  "Be brief. Skip filler words. Trim qualifications.",
    "thorough": "Provide context and trade-offs. Don't oversimplify.",
    "friendly": "Be warm and conversational. Use a human tone.",
    "formal":   "Use formal, professional language. No colloquialisms.",
    "playful":  "Be witty and lively. Lean into wordplay when it fits.",
}


def load_persona() -> dict:
    try:
        from .config import load_config
        cfg = load_config().get("persona", {})
    except Exception:
        return {"name": "", "style": "", "addendum": ""}
    return {
        "name": str(cfg.get("name", "")),
        "style": str(cfg.get("style", "")),
        "addendum": str(cfg.get("addendum", "")),
    }


def render_persona_prompt() -> str:
    """Return a string to append to the agent's system prompt.

    Empty string when no persona is configured -- caller can safely
    concatenate without checking.
    """
    p = load_persona()
    if not (p["name"] or p["style"] or p["addendum"]):
        return ""
    parts: list[str] = []
    if p["name"]:
        parts.append(f"You are {p['name']}.")
    style = (p["style"] or "").strip().lower()
    if style and style in STYLES:
        parts.append(STYLES[style])
    elif style and style not in _warned_styles:
        # A typo'd / unsupported style (e.g. "concice") would otherwise be
        # silently dropped with no feedback. Nudge once per process toward the
        # valid set rather than hard-erroring (voice-only, low stakes).
        _warned_styles.add(style)
        log.warning(
            "[persona] style %r is not recognized and was ignored; "
            "valid values: %s",
            style, " | ".join(sorted(STYLES)),
        )
    if p["addendum"]:
        parts.append(p["addendum"])
    return "\n\n# Persona\n\n" + " ".join(parts)
