"""Fleet memory: the agent-agnostic learning plane (Learning System of Record).

Maverick's learning loops were built for Maverick agents; this opens them to
ANY agent — Agentforce, Copilot, custom, open-source runtimes — so the
enterprise gets ONE governed memory across its whole fleet. Two operations:

* :func:`ingest` — an external agent deposits experience (a success, a
  failure, or an explicit lesson). Every record is schema-validated,
  size-capped, secret-redacted, Shield-scanned, provenance-tagged
  (``vendor:agent_id``), tenant-isolated, and audited. Successes/failures
  land in the fleet inbox as donation-shaped records (the dream cycle
  consolidates them alongside native experience); lessons land as
  provenance-tagged reflexions so recall surfaces them immediately.
* :func:`recall` — an external agent queries governed memory for a task.
  Reads are scoped (department boost; user-preference notes are NEVER
  exposed — they stay private to their channel/user) and every read is
  audited, so "which agent learned what, and who recalled it" is provable.

Off by default (``[fleet_memory] enable`` / ``MAVERICK_FLEET_MEMORY=1``):
exposing the memory plane to third-party agents is an explicit trust
decision. Fail-open internals, fail-closed surface (disabled = refuse;
unregistered agents = refuse).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_LEGACY_DIR = Path.home() / ".maverick" / "fleet-memory"
_MAX_TEXT = 2000
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
KINDS = ("success", "failure", "lesson")


def _dir() -> Path:
    try:
        from .paths import current_tenant, data_dir
        if current_tenant():
            return data_dir("fleet-memory")
    except Exception:  # pragma: no cover
        pass
    return _LEGACY_DIR


def inbox_dir() -> Path:
    return _dir() / "inbox"


def registry_path() -> Path:
    return _dir() / "agents.ndjson"


def enabled() -> bool:
    env = os.environ.get("MAVERICK_FLEET_MEMORY", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    try:
        from .config import load_config
        return bool((load_config().get("fleet_memory") or {}).get("enable", False))
    except Exception:  # pragma: no cover
        return False


def _sanitize(text: str, *, shield: Any | None) -> str | None:
    """Redact + Shield-scan one field; None = reject the record."""
    safe = str(text or "")[:_MAX_TEXT]
    try:
        from .safety.secret_detector import redact as _redact
        safe, _ = _redact(safe)
    except Exception:  # pragma: no cover
        pass
    if shield is not None:
        try:
            verdict = shield.scan_input(safe)
            if not getattr(verdict, "allowed", True):
                return None
        except Exception:  # pragma: no cover -- fail toward the gate
            return None
    return safe


def _audit(event: str, **payload) -> None:
    try:
        from .audit import EventKind, record
        record(EventKind.LEARNING_UPDATE, agent="fleet_memory",
               fleet=event, **payload)
    except Exception:  # pragma: no cover -- audit never blocks the plane
        pass


def register_agent(agent_id: str, vendor: str, *, description: str = "") -> bool:
    """Add an external agent to the fleet roster (idempotent)."""
    if not (_ID_RE.match(agent_id or "") and _ID_RE.match(vendor or "")):
        return False
    path = registry_path()
    source = f"{vendor}:{agent_id}"
    if any(row.get("source") == source for row in roster()):
        return True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.time(), "source": source, "vendor": vendor,
                "agent_id": agent_id, "description": str(description)[:200],
            }) + "\n")
        os.chmod(path, 0o600)
    except OSError as e:
        log.warning("fleet_memory: register failed: %s", e)
        return False
    _audit("register", source=source)
    return True


def roster() -> list[dict]:
    path = registry_path()
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                try:
                    d = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(d, dict) and d.get("source"):
                    out.append(d)
    except OSError:
        return []
    return out


def ingest(record: dict, *, shield: Any | None = None) -> tuple[bool, str]:
    """Deposit one external experience record. Returns ``(ok, reason)``.

    Schema: ``{agent_id, vendor, kind: success|failure|lesson, goal_text,
    reflection?, tools_used?, domain?}``. The source agent must be on the
    roster — an unregistered agent cannot write memory (fail-closed).
    """
    if not enabled():
        return False, "fleet memory is disabled ([fleet_memory] enable = true)"
    agent_id = str(record.get("agent_id", "") or "")
    vendor = str(record.get("vendor", "") or "")
    source = f"{vendor}:{agent_id}"
    if not any(r.get("source") == source for r in roster()):
        return False, f"unregistered fleet agent {source!r}: register it first"
    kind = str(record.get("kind", "") or "").lower()
    if kind not in KINDS:
        return False, f"kind must be one of {KINDS}"
    goal_text = _sanitize(record.get("goal_text", ""), shield=shield)
    reflection = _sanitize(record.get("reflection", ""), shield=shield)
    if goal_text is None or reflection is None:
        _audit("ingest_blocked", source=source)
        return False, "record blocked by Shield"
    if not goal_text.strip():
        return False, "goal_text is required"
    tools = [str(t)[:80] for t in (record.get("tools_used") or [])[:16]]
    domain = str(record.get("domain", "") or "") or None

    if kind == "lesson":
        from . import reflexion
        ok = reflexion.record(
            goal_text=goal_text, failure_class="fleet_lesson",
            failure_msg=f"from {source}", reflection=reflection,
            tools_used=tools, domain=domain,
        )
        _audit("ingest", source=source, kind=kind)
        return bool(ok), "ok" if ok else "write failed"

    # success / failure -> donation-shaped record in the fleet inbox; the
    # dream cycle consolidates it alongside native experience
    # (dream_cycle(donations_dir=fleet_memory.inbox_dir())).
    row = {
        "schema_version": 1, "ts": time.time(),
        "task_brief_text": goal_text,
        "outcome": "success" if kind == "success" else "failure",
        "tools_used": tools, "verifier_critique": reflection or "",
        "source": source, "vendor": vendor,
    }
    try:
        inbox = inbox_dir()
        inbox.mkdir(parents=True, exist_ok=True)
        name = f"{int(time.time() * 1000)}-{vendor}-{agent_id}.json"
        (inbox / name).write_text(json.dumps(row), encoding="utf-8")
    except OSError as e:
        log.warning("fleet_memory: ingest write failed: %s", e)
        return False, "write failed"
    _audit("ingest", source=source, kind=kind)
    return True, "ok"


def recall(
    query: str, *, agent_id: str = "", vendor: str = "",
    domain: str | None = None, shield: Any | None = None,
) -> tuple[str, str]:
    """Governed memory read for an external agent. Returns ``(context, reason)``.

    Surfaces department-boosted reflexion lessons and dream insights; never
    user-preference notes. Every read lands in the audit log with the
    reader's identity — "who recalled what" is provable.
    """
    if not enabled():
        return "", "fleet memory is disabled ([fleet_memory] enable = true)"
    source = f"{vendor}:{agent_id}"
    if not any(r.get("source") == source for r in roster()):
        return "", f"unregistered fleet agent {source!r}"
    safe_query = _sanitize(query, shield=shield)
    if safe_query is None or not safe_query.strip():
        return "", "query blocked or empty"
    blocks: list[str] = []
    try:
        from . import reflexion
        hits = reflexion.recall(safe_query, k=3, domain=domain)
        block = reflexion.format_context(hits, shield=shield)
        if block:
            blocks.append(block)
    except Exception:  # pragma: no cover
        pass
    try:
        from . import dreaming
        ins = dreaming.recall_insights(safe_query, domain=domain, k=3)
        block = dreaming.format_context(ins, shield=shield)
        if block:
            blocks.append(block)
    except Exception:  # pragma: no cover
        pass
    _audit("recall", source=source, domain=domain or "", hits=len(blocks))
    return "\n".join(blocks), "ok"


def status() -> dict:
    """Roster + per-source ingestion counts (the fleet console's data)."""
    counts: dict[str, dict[str, int]] = {}
    inbox = inbox_dir()
    if inbox.is_dir():
        for p in inbox.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            src = str(d.get("source", "") or "(unknown)")
            by = counts.setdefault(src, {"success": 0, "failure": 0})
            key = "success" if d.get("outcome") == "success" else "failure"
            by[key] += 1
    return {"agents": roster(), "ingested": counts}


__all__ = [
    "KINDS", "enabled", "register_agent", "roster", "ingest", "recall",
    "status", "inbox_dir", "registry_path",
]
