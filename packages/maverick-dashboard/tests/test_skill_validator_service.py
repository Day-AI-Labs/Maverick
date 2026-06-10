"""The skill-validator service endpoint lints a posted SKILL.md."""
from __future__ import annotations

from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})

VALID = """---
name: refund-helper
triggers:
  - process a refund
tools_needed:
  - stripe
---

# What this skill does

Issue a refund and notify the customer, then verify the ledger entry.

# Steps

1. Look up the charge. 2. Refund. 3. Verify.
"""


def test_valid_skill_passes():
    r = client.post("/api/v1/skills/validate", content=VALID.encode())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True and data["errors"] == []


def test_invalid_skill_reports_errors():
    r = client.post("/api/v1/skills/validate", content=b"no frontmatter at all")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False and data["errors"]


def test_empty_and_oversize_rejected():
    assert client.post("/api/v1/skills/validate", content=b"").status_code == 400
    big = b"x" * (256 * 1024 + 1)
    assert client.post("/api/v1/skills/validate", content=big).status_code == 413
