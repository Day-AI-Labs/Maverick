"""Skill + channel template generators (roadmap: 2027 H1 distribution).

Deterministic codegen for the two things contributors most often start from
scratch: a **skill** (a `SKILL.md` with the exact frontmatter the validator
wants) and a **channel adapter** (a `Channel` subclass with the start/send/stop
seams wired). Emitting a known-good scaffold means a new author edits prose
instead of fighting the frontmatter schema or the adapter contract.

Offline and deterministic — the skill output passes ``maverick skill validate``
as-is; the channel output is import-clean Python.

ops:
  - skill(name, triggers[, tools_needed, summary])  — render a valid SKILL.md.
  - channel(name[, transport])                      — render a Channel adapter.
"""
from __future__ import annotations

import re
from typing import Any

from . import Tool

_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _to_kebab(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)


def _to_class(name: str) -> str:
    parts = re.split(r"[^a-zA-Z0-9]+", str(name).strip())
    return "".join(p[:1].upper() + p[1:] for p in parts if p) or "My"


def _gen_skill(args: dict[str, Any]) -> str:
    name = _to_kebab(args.get("name", ""))
    if not name or not _KEBAB.match(name):
        return "ERROR: name must produce a kebab-case id (letters/digits/hyphens)"
    triggers = args.get("triggers")
    if not isinstance(triggers, list) or not any(str(t).strip() for t in triggers):
        return "ERROR: at least one trigger phrase is required"
    tools = [str(t).strip() for t in (args.get("tools_needed") or []) if str(t).strip()]
    summary = str(args.get("summary") or f"Automate the '{name}' task.").strip()

    lines = ["---", f"name: {name}", "triggers:"]
    lines += [f"  - {str(t).strip()}" for t in triggers if str(t).strip()]
    if tools:
        lines.append("tools_needed:")
        lines += [f"  - {t}" for t in tools]
    lines.append("---")
    lines.append("")
    lines.append(f"# What this skill does\n\n{summary}\n")
    lines.append("# Steps\n\n1. Describe the first concrete step.\n"
                 "2. Describe the next step.\n3. Verify the result.\n")
    lines.append("# Notes\n\nEdit these sections with the real procedure before publishing.")
    return "\n".join(lines)


def _gen_channel(args: dict[str, Any]) -> str:
    raw = str(args.get("name", "")).strip()
    if not raw:
        return "ERROR: name is required"
    cls = _to_class(raw) + "Channel"
    key = _to_kebab(raw).replace("-", "_") or "mychannel"
    transport = str(args.get("transport") or "polling").strip()

    return f'''"""{cls} — generated channel adapter scaffold.

Transport: {transport}. Fill in the TODOs to connect a real platform.

Config::

    [channels.{key}]
    enabled = true
    token = "${{{key.upper()}_TOKEN}}"

Requires::

    pip install 'maverick-channels'
"""
from __future__ import annotations

import logging

from .base import Channel, IncomingMessage, is_allowed, normalize_allowlist

log = logging.getLogger(__name__)


class {cls}(Channel):
    """Adapter for the {key} platform."""

    def __init__(self, token: str | None = None, allowed_user_ids=None):
        self.token = token
        self.allowlist = normalize_allowlist(allowed_user_ids, "{key.upper()}_ALLOWED_USER_IDS")
        self._on_message = None

    def on_message(self, handler) -> None:
        """Register the coroutine the agent loop hands incoming messages to."""
        self._on_message = handler

    async def start(self) -> None:
        # TODO: connect to the platform and dispatch each inbound message:
        #   msg = IncomingMessage(user_id=..., text=..., channel="{key}")
        #   if is_allowed(msg.user_id, self.allowlist) and self._on_message:
        #       await self._on_message(msg)
        raise NotImplementedError("implement {key} start()")

    async def send(self, user_id: str, text: str) -> None:
        # TODO: deliver `text` to `user_id` on the platform.
        raise NotImplementedError("implement {key} send()")

    async def stop(self) -> None:
        # TODO: close any open connections.
        return None
'''


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if op == "skill":
        return _gen_skill(args)
    if op == "channel":
        return _gen_channel(args)
    return f"ERROR: unknown op {op!r} (expected 'skill' or 'channel')"


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["skill", "channel"]},
        "name": {"type": "string", "description": "skill id / channel name"},
        "triggers": {"type": "array", "items": {"type": "string"}, "description": "skill: activation phrases"},
        "tools_needed": {"type": "array", "items": {"type": "string"}, "description": "skill: tools it calls"},
        "summary": {"type": "string", "description": "skill: one-line description"},
        "transport": {"type": "string", "description": "channel: transport hint (polling/webhook)"},
    },
    "required": ["op", "name"],
}


def template_generator() -> Tool:
    return Tool(
        name="template_generator",
        description=(
            "Generate a skill or channel-adapter scaffold. op=skill (needs "
            "'name' + 'triggers', optional 'tools_needed'/'summary') renders a "
            "valid SKILL.md. op=channel (needs 'name', optional 'transport') "
            "renders a Channel subclass with start/send/stop seams. "
            "Deterministic codegen; no model."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
