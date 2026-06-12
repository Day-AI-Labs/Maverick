"""Memory-safe parsing of untrusted bytes (roadmap: 2027 H2 safety).

The parsers that touch **attacker-controllable bytes** — PDFs from
attachments, images from channels, HTML from fetched pages — are largely
C-extension-backed (pdfplumber/pdfminer, pypdf, Pillow, lxml). A memory-safety
bug there is an in-process RCE/corruption foothold fed directly by untrusted
input. Rewriting those parsers isn't realistic; **isolating** them is:

* :data:`PARSERS` — the inventory: each untrusted-input parser path, what
  feeds it, and whether its implementation is memory-safe (pure Python) or
  C-extension (isolate-worthy). The policy, in code.
* :func:`parse_isolated` — run a whitelisted parser entry point in a child
  Python process with the **secret-scrubbed env** (same posture as plugin
  isolation): a separate address space, so a heap bug or segfault on hostile
  bytes kills the child — never the kernel — and an exploited parser child
  holds no provider keys. Input goes over stdin (bytes), result over stdout
  (JSON), size caps enforced BEFORE the child sees the data, hard timeout.
* Opt-in: ``[security] isolate_parsers = true`` (env
  ``MAVERICK_ISOLATE_PARSERS``). Off by default — in-process behavior is
  byte-identical; turning it on routes the registered consumers through the
  child. ``should_isolate()`` is the gate consumers check.

Only entries in :data:`PARSERS` may run in the child (a whitelist keyed by
name — never an arbitrary dotted path from the model).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

MAX_INPUT_BYTES = 64 * 1024 * 1024   # refuse absurd inputs before any parse
DEFAULT_TIMEOUT = 60.0


@dataclass(frozen=True)
class ParserEntry:
    name: str          # whitelist key
    module: str        # module imported INSIDE the child
    func: str          # function(data: bytes, **kwargs) -> JSON-able result
    feeds: str         # what untrusted source reaches it
    memory_safe: bool  # pure-Python (True) vs C-extension-backed (False)


# The inventory/policy: untrusted-input parsers and their safety class.
PARSERS: dict[str, ParserEntry] = {
    "pdf_text": ParserEntry(
        name="pdf_text",
        module="maverick.tools.pdf_reader",
        func="extract_text_from_bytes",
        feeds="attachments / channel uploads",
        memory_safe=False,  # pdfplumber(pdfminer)/pypdf C-accelerated paths
    ),
    "image_meta": ParserEntry(
        name="image_meta",
        module="maverick.parser_isolation",
        func="_probe_image_meta",
        feeds="channel image uploads",
        memory_safe=False,  # Pillow decoders are C
    ),
}


def should_isolate() -> bool:
    if os.environ.get("MAVERICK_ISOLATE_PARSERS", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return True
    try:
        from .config import load_config
        return bool(((load_config() or {}).get("security") or {})
                    .get("isolate_parsers", False))
    except Exception:  # pragma: no cover -- config never blocks parsing
        return False


_CHILD_TEMPLATE = """\
import json, sys
sys.path.insert(0, {import_root!r})
data = sys.stdin.buffer.read()
from importlib import import_module
fn = getattr(import_module({module!r}), {func!r})
kwargs = json.loads({kwargs_json!r})
try:
    result = fn(data, **kwargs)
    sys.stdout.write(json.dumps({{"ok": True, "result": result}}))
except Exception as e:
    sys.stdout.write(json.dumps({{"ok": False,
                                  "error": f"{{type(e).__name__}}: {{e}}"}}))
"""


def parse_isolated(name: str, data: bytes, *, timeout: float = DEFAULT_TIMEOUT,
                   **kwargs):
    """Run the whitelisted parser ``name`` on ``data`` in a scrubbed child.

    Returns the parser's JSON-able result. Raises ``ValueError`` for an
    unknown parser or oversized input, ``RuntimeError`` for a child that
    crashed/timed out/errored — the caller decides whether to fall back.
    """
    entry = PARSERS.get(name)
    if entry is None:
        raise ValueError(f"unknown parser {name!r}; whitelisted: {sorted(PARSERS)}")
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError(
            f"input of {len(data)} bytes exceeds the {MAX_INPUT_BYTES}-byte cap")
    # kwargs are baked as a JSON literal — nothing user-controlled becomes code.
    # The child runs in isolated mode with a neutral cwd, then imports Maverick
    # from the same trusted package root as this parent module.  That keeps
    # python -c from resolving whitelisted dotted names through an attacker
    # controlled workspace package.
    import_root = str(Path(__file__).resolve().parents[1])
    code = _CHILD_TEMPLATE.format(
        import_root=import_root, module=entry.module, func=entry.func,
        kwargs_json=json.dumps(kwargs, default=str),
    )
    from .tools import scrub_child_env
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
            input=data, capture_output=True, timeout=timeout,
            env=scrub_child_env(), cwd=os.path.abspath(os.sep),
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"parser {name!r} timed out after {timeout}s") from e
    if proc.returncode != 0:
        # a segfault/abort on hostile bytes lands HERE, not in the kernel
        raise RuntimeError(
            f"parser child {name!r} died (exit {proc.returncode}): "
            f"{proc.stderr.decode('utf-8', 'replace')[-200:]}")
    try:
        payload = json.loads(proc.stdout.decode("utf-8"))
    except ValueError as e:
        raise RuntimeError(f"parser {name!r} returned non-JSON output") from e
    if not payload.get("ok"):
        raise RuntimeError(f"parser {name!r} failed: {payload.get('error')}")
    return payload.get("result")


def _probe_image_meta(data: bytes) -> dict:
    """Child-side image probe: format/size via Pillow without full decode."""
    import io
    try:
        from PIL import Image
    except ImportError as e:  # pragma: no cover -- optional extra
        raise RuntimeError("Pillow not installed ([computer-use] extra)") from e
    with Image.open(io.BytesIO(data)) as im:
        return {"format": im.format, "width": im.width, "height": im.height,
                "mode": im.mode}


def inventory() -> str:
    """Render the parser policy table (the auditable inventory)."""
    lines = ["untrusted-input parsers:"]
    for e in sorted(PARSERS.values(), key=lambda e: e.name):
        safety = "memory-safe (pure python)" if e.memory_safe else \
            "C-extension — ISOLATE"
        lines.append(f"  {e.name:<12} {e.module}.{e.func}")
        lines.append(f"      feeds: {e.feeds}; {safety}")
    state = "ON" if should_isolate() else \
        "off (opt in via [security] isolate_parsers)"
    lines.append(f"isolation: {state}")
    return "\n".join(lines)


__all__ = ["PARSERS", "ParserEntry", "parse_isolated", "should_isolate",
           "inventory", "MAX_INPUT_BYTES"]
