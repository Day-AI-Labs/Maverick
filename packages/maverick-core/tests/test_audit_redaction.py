"""Audit log redaction — secrets in payloads never land on disk in plaintext."""
from __future__ import annotations

import json
from pathlib import Path


def _read_first(path: Path) -> dict:
    return json.loads(path.read_text().splitlines()[0])


def test_anthropic_key_redacted(tmp_path: Path):
    from maverick.audit.events import AuditEvent, EventKind
    from maverick.audit.writer import AuditLog

    al = AuditLog(audit_dir=tmp_path)
    al.record(AuditEvent(
        ts=1.0, kind=EventKind.TOOL_RESULT,
        payload={"name": "shell",
                 "output_summary": "leaked: sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
    ))
    files = list(tmp_path.glob("*.ndjson"))
    assert len(files) == 1
    row = _read_first(files[0])
    assert "sk-ant-api03-AAAAAA" not in json.dumps(row)
    assert "[REDACTED" in row["output_summary"]


def test_openai_key_redacted(tmp_path: Path):
    from maverick.audit.events import AuditEvent, EventKind
    from maverick.audit.writer import AuditLog

    al = AuditLog(audit_dir=tmp_path)
    al.record(AuditEvent(
        ts=2.0, kind=EventKind.TOOL_RESULT,
        payload={"name": "shell",
                 "output_summary": "key: sk-proj-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
    ))
    row = _read_first(list(tmp_path.glob("*.ndjson"))[0])
    body = json.dumps(row)
    assert "sk-proj-AAA" not in body
    assert "[REDACTED" in row["output_summary"]


def test_redaction_walks_nested_lists_and_dicts(tmp_path: Path):
    from maverick.audit.events import AuditEvent, EventKind
    from maverick.audit.writer import AuditLog

    al = AuditLog(audit_dir=tmp_path)
    al.record(AuditEvent(
        ts=3.0, kind=EventKind.TOOL_RESULT,
        payload={
            "name": "shell",
            "nested": {
                "deeper": ["one", "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"],
            },
        },
    ))
    row = _read_first(list(tmp_path.glob("*.ndjson"))[0])
    body = json.dumps(row)
    assert "ghp_AAA" not in body


def test_redaction_no_secrets_passes_through_unchanged(tmp_path: Path):
    from maverick.audit.events import AuditEvent, EventKind
    from maverick.audit.writer import AuditLog

    al = AuditLog(audit_dir=tmp_path)
    al.record(AuditEvent(
        ts=4.0, kind=EventKind.TOOL_RESULT,
        payload={"name": "shell", "output_summary": "ls /tmp -- nothing of interest"},
    ))
    row = _read_first(list(tmp_path.glob("*.ndjson"))[0])
    assert row["output_summary"] == "ls /tmp -- nothing of interest"
    assert row["name"] == "shell"
