"""Fast JSON with a stdlib fallback (roadmap: 2028 H1 performance —
"sub-ms dispatch overhead (msgspec/orjson)").

The dispatch path serializes/deserializes JSON constantly (tool args/results,
event payloads, world-model blobs). ``orjson`` is ~5-10x faster than the
stdlib ``json`` for both directions; ``msgspec`` similar. This is a single
drop-in seam — ``dumps`` / ``loads`` — that prefers the fast backend when
installed and is **semantically identical to stdlib json** so it's safe to use
anywhere: ``dumps`` returns ``str`` (orjson natively returns ``bytes`` — we
decode), honors ``sort_keys``, and falls back to stdlib on any value orjson
can't take (orjson is stricter about dict key types / non-str keys).

No new required dependency: ``[perf-fastjson] = ["orjson>=3.9"]`` is an opt-in
extra; with it absent everything routes through stdlib ``json`` unchanged.
``backend()`` reports which is active (for a metric / startup log).
"""
from __future__ import annotations

import json as _json
from typing import Any

try:  # orjson is the optional fast backend ([perf-fastjson] extra).
    import orjson as _orjson
except Exception:  # pragma: no cover -- absence is the common/default case
    _orjson = None


def backend() -> str:
    return "orjson" if _orjson is not None else "stdlib"


def dumps(obj: Any, *, sort_keys: bool = False) -> str:
    """Serialize ``obj`` to a JSON ``str`` (stdlib-compatible output).

    Uses orjson when available; falls back to stdlib for any object orjson
    rejects (e.g. non-str dict keys, custom types stdlib handles via
    ``default=str`` below) so a caller never has to care which backend is on.
    """
    if _orjson is not None:
        opt = _orjson.OPT_SORT_KEYS if sort_keys else 0
        try:
            return _orjson.dumps(obj, option=opt).decode("utf-8")
        except TypeError:
            pass  # orjson is stricter; fall through to stdlib
    return _json.dumps(obj, sort_keys=sort_keys, default=str)


def loads(data: str | bytes) -> Any:
    """Parse JSON from ``str``/``bytes``. orjson when available, else stdlib."""
    if _orjson is not None:
        try:
            return _orjson.loads(data)
        except Exception:
            pass
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return _json.loads(data)


__all__ = ["dumps", "loads", "backend"]
