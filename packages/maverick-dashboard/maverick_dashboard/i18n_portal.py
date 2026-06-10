"""i18n community portal (roadmap: 2027 H2 UX).

The chrome catalog (``i18n.MESSAGES``, en/fr/de/ja/zh) ships in-tree; this is
the **community on-ramp** for adding a language without touching Python:

* **Contribution scaffold** — :func:`scaffold` emits a ready-to-fill JSON
  catalog for a new language (every English key, values pre-seeded with the
  English string so a partial translation is still valid).
* **Validation** — :func:`validate_catalog` lints a submitted catalog against
  the English reference (lang code shape, missing/unknown keys, blank values,
  and unbalanced ``{placeholder}`` tokens that would break a format string) so
  a maintainer (or a CI check on a translation PR) gets a precise diff.
* **Load external catalogs** — :func:`load_external_catalogs` reads validated
  ``<lang>.json`` files from ``[i18n] portal_dir`` (or
  ``MAVERICK_I18N_DIR``) and :func:`merged_messages` overlays them onto the
  built-ins, so an operator drops a community translation in a directory and
  the dashboard speaks it — no rebuild. A malformed catalog is skipped with a
  warning (never blanks the UI).

Stdlib only; offline and deterministic.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from . import i18n

log = logging.getLogger(__name__)

_LANG_CODE = re.compile(r"^[a-z]{2}(-[a-z]{2})?$")
_PLACEHOLDER = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def reference_keys() -> list[str]:
    """The English reference key set every catalog must cover."""
    return sorted(i18n.MESSAGES)


def scaffold(lang: str) -> dict[str, str]:
    """A fill-in catalog for ``lang``: every key, seeded with the English text."""
    return {key: i18n.MESSAGES[key].get("en", key) for key in reference_keys()}


def validate_catalog(lang: str, catalog: dict) -> list[str]:
    """Lint a submitted ``{key: text}`` catalog. Returns problems ([] == OK)."""
    problems: list[str] = []
    if not isinstance(lang, str) or not _LANG_CODE.match(lang):
        problems.append(f"invalid language code {lang!r} (expected e.g. 'es' or 'pt-br')")
    if not isinstance(catalog, dict):
        return problems + ["catalog must be a JSON object of key -> text"]
    ref = set(reference_keys())
    have = set(catalog)
    for key in sorted(ref - have):
        problems.append(f"missing key: {key}")
    for key in sorted(have - ref):
        problems.append(f"unknown key (not in reference): {key}")
    for key in sorted(have & ref):
        val = catalog[key]
        if not isinstance(val, str) or not val.strip():
            problems.append(f"{key}: value must be a non-empty string")
            continue
        want = set(_PLACEHOLDER.findall(i18n.MESSAGES[key].get("en", "")))
        got = set(_PLACEHOLDER.findall(val))
        if want != got:
            problems.append(
                f"{key}: placeholder mismatch (expected {sorted(want)}, got {sorted(got)})")
    return problems


def _portal_dir() -> Path | None:
    env = os.environ.get("MAVERICK_I18N_DIR", "").strip()
    if env:
        return Path(env)
    try:
        from maverick.config import load_config
        d = ((load_config() or {}).get("i18n") or {}).get("portal_dir")
        return Path(d) if d else None
    except Exception:  # pragma: no cover -- config never blocks the dashboard
        return None


def load_external_catalogs(portal_dir: Path | None = None) -> dict[str, dict[str, str]]:
    """Load validated ``<lang>.json`` catalogs from the portal dir.

    Returns ``{lang: {key: text}}`` for every catalog that passes validation;
    an invalid or unreadable file is skipped with a warning. Only keys present
    in the reference set are kept (so a stray key can't reach the UI).
    """
    portal_dir = portal_dir or _portal_dir()
    out: dict[str, dict[str, str]] = {}
    if portal_dir is None or not Path(portal_dir).is_dir():
        return out
    ref = set(reference_keys())
    for path in sorted(Path(portal_dir).glob("*.json")):
        lang = path.stem.lower()
        try:
            catalog = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("i18n portal: skipping %s (%s)", path.name, e)
            continue
        problems = validate_catalog(lang, catalog)
        if problems:
            log.warning("i18n portal: skipping %s (%d problem(s): %s)",
                        path.name, len(problems), problems[0])
            continue
        out[lang] = {k: v for k, v in catalog.items() if k in ref}
    return out


def merged_messages(portal_dir: Path | None = None) -> dict[str, dict[str, str]]:
    """``i18n.MESSAGES`` with external community catalogs overlaid.

    Built-ins win nothing/lose nothing for shipped languages unless a catalog
    re-supplies a key for a NEW language; external langs are added per key.
    The result has the same ``{key: {lang: text}}`` shape ``i18n.t`` reads.
    """
    merged: dict[str, dict[str, str]] = {
        key: dict(langs) for key, langs in i18n.MESSAGES.items()
    }
    for lang, catalog in load_external_catalogs(portal_dir).items():
        for key, text in catalog.items():
            if key in merged:
                merged[key].setdefault(lang, text)
    return merged


def available_languages(portal_dir: Path | None = None) -> list[str]:
    """Built-in + community languages, sorted."""
    langs = set(i18n.LANGS) | set(load_external_catalogs(portal_dir))
    return sorted(langs)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- CLI shell
    import argparse
    p = argparse.ArgumentParser(prog="maverick_dashboard.i18n_portal")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scaffold", help="print a fill-in catalog for a language")
    s.add_argument("lang")
    v = sub.add_parser("validate", help="validate a <lang>.json catalog file")
    v.add_argument("path")
    args = p.parse_args(argv)
    if args.cmd == "scaffold":
        print(json.dumps(scaffold(args.lang), ensure_ascii=False, indent=2))
        return 0
    path = Path(args.path)
    catalog = json.loads(path.read_text(encoding="utf-8"))
    problems = validate_catalog(path.stem.lower(), catalog)
    if problems:
        for prob in problems:
            print(f"INVALID: {prob}")
        return 1
    print(f"{path.name}: OK ({len(catalog)} keys)")
    return 0


__all__ = ["reference_keys", "scaffold", "validate_catalog",
           "load_external_catalogs", "merged_messages", "available_languages"]
