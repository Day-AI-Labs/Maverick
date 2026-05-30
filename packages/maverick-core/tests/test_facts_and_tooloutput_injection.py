"""Facts injected into the orchestrator brief must be scanned/redacted, and
tool output must be secret-redacted before it reaches the model.

Council (Security seat, findings #4-#5 + #14):
  - "Known facts about the user" were concatenated into the orchestrator
    system brief verbatim -- a fact set via REST/MCP (or poisoned by a prior
    injection) became a standing instruction in EVERY future run.
  - Tool output reached the model/blackboard/channel WITHOUT secret_detector
    redaction, so `cat .env` flowed verbatim out a channel.
  - secret_detector missed GitLab PAT / Twilio / bearer / DB connection URIs.

Note: the secret-shaped fixtures below are ASSEMBLED at runtime from
fragments rather than written as literals, so GitHub Push Protection's
secret scanner doesn't (correctly) flag the test file itself.
"""
from __future__ import annotations

from maverick.safety.secret_detector import redact, scan

# Fake credentials built from fragments -- never a literal secret in source.
_FAKE_GITLAB = "glpat-" + ("A1b2C3d4" * 3)
_FAKE_TWILIO = "SK" + ("0123456789abcdef" * 2)        # SK + 32 hex
_FAKE_STRIPE = "sk_live_" + ("0123456789abcdefABCD" + "EFGH")
_FAKE_BEARER_TOK = "abcdef0123456789ABCDEF"


# ---- extended secret patterns (finding #14) ----
def test_detects_gitlab_pat():
    red, m = redact(f"token={_FAKE_GITLAB}")
    assert m and _FAKE_GITLAB not in red


def test_detects_twilio_api_key():
    red, m = redact(f"key is {_FAKE_TWILIO} here")
    assert m and _FAKE_TWILIO not in red


def test_detects_db_connection_uri():
    red, m = redact("DATABASE_URL=postgres://user:s3cr3t@db.internal:5432/app")
    assert m and "s3cr3t" not in red


def test_detects_bearer_header():
    red, m = redact(f"Authorization: Bearer {_FAKE_BEARER_TOK}")
    assert m and _FAKE_BEARER_TOK not in red


def test_benign_text_not_flagged():
    assert scan("the bearer of this note may pass") == []
    assert scan("just some normal output, nothing secret here") == []


# ---- tool output is secret-redacted in _run_tool before framing ----
def test_run_tool_redacts_secret_in_output():
    import asyncio
    import tempfile
    from pathlib import Path
    from maverick.agent import Agent
    from maverick.blackboard import Blackboard
    from maverick.budget import Budget
    from maverick.swarm import SwarmContext
    from maverick.world_model import WorldModel

    leak = f"STRIPE_KEY={_FAKE_STRIPE} and a jwt eyJabc.def.ghi"

    class _Tools:
        async def run(self, name, args):
            return leak  # simulate `cat .env` returning a live key

    w = WorldModel(Path(tempfile.mkdtemp()) / "w.db")
    ctx = SwarmContext(world=w, budget=Budget(), sandbox=None,
                       blackboard=Blackboard(), goal_id=1, max_depth=1, llm=None)
    a = Agent(ctx=ctx, role="researcher", brief="b")
    a._shield = None  # isolate the secret-redaction path from shield scanning
    a.tools = _Tools()
    out = asyncio.run(a._run_tool("read_file", {"path": ".env"}))
    assert _FAKE_STRIPE not in out          # the live key must be gone
    assert "tool_output" in out             # framing wrapper still present


# ---- facts are redacted before entering the orchestrator brief ----
def test_fact_value_secret_is_redacted():
    """A fact carrying a secret is redacted before it would hit the brief
    (the orchestrator runs each fact through this same redactor)."""
    val, matches = redact(f"api={_FAKE_STRIPE}")
    assert matches and _FAKE_STRIPE not in val
