"""Dashboard-owned registry of inbound webhook triggers.

A trigger binds a saved template (plus operator-set default params) to a name.
An HMAC-signed POST to ``/webhook/run`` with that name renders the template and
runs it as a goal (the inbound body may override *declared* params at fire
time). Persisted to ``~/.maverick/dashboard-triggers.toml`` -- dashboard-owned,
like the Settings overlay, and deliberately NOT merged into the kernel config
(``load_config`` never reads it). Mirrors ``settings_store``'s atomic, 0600
write and hand-rolled TOML so we add no serialization dependency.

Params are stored as a JSON string inside the TOML table to avoid hand-rolling
nested tables; ``list_triggers`` decodes them back to a dict.
"""
from __future__ import annotations

import json
import re
import threading
import time

from maverick import config

# Serializes the triggers load-modify-save in-process; cross_process_lock in
# _locked() extends it across processes (multiple dashboard workers).
_TRIGGERS_LOCK = threading.Lock()


def _locked():
    from contextlib import ExitStack

    from maverick.file_lock import cross_process_lock
    stack = ExitStack()
    stack.enter_context(_TRIGGERS_LOCK)
    stack.enter_context(cross_process_lock(_path()))
    return stack

# Trigger names are URL/TOML-safe slugs: they appear in the signed webhook body
# and as a bare TOML table key, so keep them to [a-z0-9-].
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


def _tomllib():
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - 3.10 fallback
        import tomli as tomllib  # type: ignore
    return tomllib


def _path():
    # Next to the Settings overlay (~/.maverick), resolved dynamically so a
    # patched HOME/MAVERICK_HOME (test isolation) is honored.
    return config.dashboard_overrides_path().parent / "dashboard-triggers.toml"


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", (name or "").strip().lower()).strip("-")
    return s[:48]


def list_triggers() -> list[dict]:
    """Every registered trigger as ``{name, template, params, created}``."""
    p = _path()
    if not p.exists():
        return []
    try:
        with open(p, "rb") as f:
            raw = _tomllib().load(f)
    except (OSError, ValueError):
        return []
    out: list[dict] = []
    for name, t in (raw.get("trigger") or {}).items():
        if not isinstance(t, dict):
            continue
        try:
            params = json.loads(t.get("params") or "{}")
        except ValueError:
            params = {}
        out.append({
            "name": name,
            "template": str(t.get("template") or ""),
            "params": params if isinstance(params, dict) else {},
            "created": float(t.get("created") or 0.0),
        })
    out.sort(key=lambda t: (t["created"], t["name"]))
    return out


def get_trigger(name: str) -> dict | None:
    for t in list_triggers():
        if t["name"] == name:
            return t
    return None


def _dump(triggers: list[dict]) -> str:
    lines = [
        "# Dashboard-managed inbound webhook triggers. Edit via the workflow",
        "# builder, not by hand. Your config.toml is never touched.",
        "",
    ]
    for t in sorted(triggers, key=lambda x: x["name"]):
        params_json = json.dumps(t.get("params") or {}, sort_keys=True)
        lines.append(f"[trigger.{t['name']}]")
        lines.append(f"template = {json.dumps(str(t['template']))}")
        lines.append(f"params = {json.dumps(params_json)}")
        lines.append(f"created = {float(t.get('created') or 0.0)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write(triggers: list[dict]) -> None:
    # Unique temp + os.replace (0600): the fixed ".toml.tmp" collided between two
    # concurrent workers. RMW serialization is in the mutators via _locked().
    from maverick.file_lock import atomic_write_text
    atomic_write_text(_path(), _dump(triggers))


def set_trigger(name: str, template: str, params: dict | None = None) -> dict:
    """Create or replace a trigger (by slugified name). Raises ValueError on a
    name that can't be made into a valid slug."""
    slug = slugify(name)
    if not _NAME_RE.match(slug):
        raise ValueError("trigger name must contain a letter or digit (a-z, 0-9, -)")
    rec = {
        "name": slug,
        "template": str(template),
        "params": {str(k): str(v) for k, v in (params or {}).items()},
        "created": time.time(),
    }
    with _locked():
        kept = [t for t in list_triggers() if t["name"] != slug]
        kept.append(rec)
        _write(kept)
    return rec


def delete_trigger(name: str) -> bool:
    with _locked():
        triggers = list_triggers()
        kept = [t for t in triggers if t["name"] != name]
        if len(kept) == len(triggers):
            return False
        _write(kept)
    return True
