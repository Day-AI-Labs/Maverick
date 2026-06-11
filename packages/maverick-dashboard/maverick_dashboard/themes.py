"""Pluggable themes (roadmap 2028-H1 UX — "pluggable themes API").

Operators define extra dashboard themes in ``~/.maverick/config.toml``::

    [dashboard.themes.midnight]
    bg = "#101020"
    panel = "#181830"
    text = "#e0e0f0"
    accent = "#7aa2f7"

Each theme becomes a ``body.theme-<name>`` CSS-variable block rendered into
``base.html`` and is selectable exactly like the built-ins (``?theme=`` /
``mvk_theme`` cookie / ``[dashboard] theme``). Default-off: no ``themes``
table, no change.

Config is untrusted styling input, so validation is strict-by-construction:
theme names must be short slugs (they land in a body class and a CSS
selector) and every value must be a ``#rgb``/``#rrggbb`` hex color — anything
else drops the whole theme, so config can never inject CSS (no ``url(...)``,
no ``;}``-escapes, no expressions).
"""
from __future__ import annotations

import re

# The four core variables every theme must define, plus optional extras that
# map onto the rest of base.html's palette. Anything outside this set
# invalidates the theme.
REQUIRED_KEYS = ("bg", "panel", "text", "accent")
OPTIONAL_KEYS = ("border", "muted", "warn", "danger")
_ALLOWED_KEYS = frozenset(REQUIRED_KEYS) | frozenset(OPTIONAL_KEYS)

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

# Built-in body.theme-* presets in base.html; a custom theme may not shadow one.
BUILTIN_THEMES = frozenset({"dark", "light", "solarized", "hicontrast"})


def _valid_theme(name: str, values: dict) -> bool:
    if not _NAME.match(name) or name in BUILTIN_THEMES:
        return False
    if not isinstance(values, dict) or not values:
        return False
    keys = {str(k) for k in values}
    if not keys <= _ALLOWED_KEYS or not set(REQUIRED_KEYS) <= keys:
        return False
    return all(isinstance(v, str) and _HEX.match(v) for v in values.values())


def custom_themes() -> dict[str, dict[str, str]]:
    """The operator's validated ``[dashboard] themes`` table (``{}`` when
    unset, unreadable, or nothing survives validation)."""
    try:
        from maverick.config import load_config
        raw = ((load_config() or {}).get("dashboard") or {}).get("themes") or {}
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for name, values in raw.items():
        name = str(name).strip().lower()
        if _valid_theme(name, values):
            out[name] = {str(k): str(v) for k, v in values.items()}
    return out


def theme_css(themes: dict[str, dict[str, str]]) -> str:
    """Render validated themes as ``body.theme-<name>`` CSS-variable blocks.

    Only call with :func:`custom_themes` output (or equally validated data):
    names and hex values are interpolated verbatim.
    """
    blocks: list[str] = []
    for name in sorted(themes):
        decls = "; ".join(
            f"--{key}: {themes[name][key]}"
            for key in (*REQUIRED_KEYS, *OPTIONAL_KEYS)
            if key in themes[name]
        )
        blocks.append(f"body.theme-{name} {{ {decls}; }}")
    return "\n".join(blocks)


__all__ = ["custom_themes", "theme_css", "BUILTIN_THEMES", "REQUIRED_KEYS", "OPTIONAL_KEYS"]
