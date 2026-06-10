"""Cryptographic budget receipts: mint/verify roundtrip, tamper detection,
hash-chained append-only ledger, missing-key refusal. Offline and
deterministic — the world model is faked and the clock injected.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from maverick import budget_receipts as br

KEY = "test-receipt-key"


@dataclass
class FakeEpisode:
    """Mirrors maverick.world_model.EpisodeSpend's spend fields."""

    id: int
    goal_id: int
    started_at: float
    ended_at: float | None
    outcome: str | None
    cost_dollars: float
    input_tokens: int
    output_tokens: int
    tool_calls: int


class FakeWorld:
    def __init__(self, episodes):
        self._episodes = list(episodes)

    def list_episodes(self, limit=50, goal_id=None):
        eps = [e for e in self._episodes if goal_id is None or e.goal_id == goal_id]
        return eps[:limit]


def _world():
    return FakeWorld([
        FakeEpisode(1, 7, 100.0, 160.0, "ok", 1.25, 1000, 200, 3),
        FakeEpisode(2, 7, 200.0, 260.0, "ok", 0.75, 500, 100, 2),
        FakeEpisode(3, 9, 300.0, 360.0, "ok", 99.0, 9, 9, 9),  # other goal
    ])


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch, tmp_path):
    monkeypatch.delenv("MAVERICK_RECEIPT_KEY", raising=False)
    monkeypatch.setenv("MAVERICK_CONFIG", str(tmp_path / "nonexistent.toml"))


# --- mint / verify ----------------------------------------------------------

def test_mint_verify_roundtrip(tmp_path):
    path = tmp_path / "receipts.jsonl"
    line = br.mint(_world(), 7, KEY, path=path, clock=lambda: 999.0)
    assert br.verify(line, KEY) == br.VALID
    payload = json.loads(line)["payload"]
    assert payload["goal_id"] == 7
    assert payload["total_dollars"] == 2.0          # 1.25 + 0.75; goal 9 excluded
    assert payload["in_tokens"] == 1500
    assert payload["out_tokens"] == 300
    assert payload["tool_calls"] == 5
    assert payload["started_at"] == 100.0
    assert payload["ended_at"] == 260.0
    assert payload["minted_at"] == 999.0
    assert payload["prev_receipt_hash"] is None     # genesis


def test_budget_caps_embedded_from_config(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[budget]\nmax_dollars = 5.0\n", encoding="utf-8")
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
    line = br.mint(_world(), 7, KEY, path=tmp_path / "r.jsonl")
    assert json.loads(line)["payload"]["budget_caps"] == {"max_dollars": 5.0}


def test_tampered_receipt_is_invalid(tmp_path):
    line = br.mint(_world(), 7, KEY, path=tmp_path / "r.jsonl")
    doctored = json.loads(line)
    doctored["payload"]["total_dollars"] = 0.01     # shave the bill
    assert br.verify(json.dumps(doctored), KEY) == br.INVALID


def test_wrong_key_is_invalid(tmp_path):
    line = br.mint(_world(), 7, KEY, path=tmp_path / "r.jsonl")
    assert br.verify(line, "some-other-key") == br.INVALID


@pytest.mark.parametrize("blob", ["not json", "[]", '{"payload": 3}', '{"sig": "x"}'])
def test_malformed_receipts(blob):
    assert br.verify(blob, KEY) == br.MALFORMED


# --- key resolution ---------------------------------------------------------

def test_mint_refuses_without_key(tmp_path):
    with pytest.raises(br.ReceiptKeyMissing, match="MAVERICK_RECEIPT_KEY"):
        br.mint(_world(), 7, path=tmp_path / "r.jsonl")


def test_key_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_RECEIPT_KEY", "env-key")
    line = br.mint(_world(), 7, path=tmp_path / "r.jsonl")
    assert br.verify(line, "env-key") == br.VALID


def test_key_env_wins_over_config(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[safety]\nreceipt_key = "config-key"\n', encoding="utf-8")
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
    assert br.resolve_key() == "config-key"
    monkeypatch.setenv("MAVERICK_RECEIPT_KEY", "env-key")
    assert br.resolve_key() == "env-key"


# --- chain ------------------------------------------------------------------

def test_chain_append_and_verify(tmp_path):
    path = tmp_path / "receipts.jsonl"
    for goal in (7, 9, 7):
        br.mint(_world(), goal, KEY, path=path)
    report = br.verify_chain(path, KEY)
    assert report.ok and report.count == 3 and report.broken_at is None
    # Each receipt embeds the hash of the line before it.
    lines = path.read_text(encoding="utf-8").splitlines()
    second = json.loads(lines[1])["payload"]["prev_receipt_hash"]
    assert second == br._receipt_hash(lines[0])


def test_chain_break_on_edited_middle_line(tmp_path):
    path = tmp_path / "receipts.jsonl"
    for goal in (7, 9, 7):
        br.mint(_world(), goal, KEY, path=path)
    lines = path.read_text(encoding="utf-8").splitlines()
    doctored = json.loads(lines[1])
    doctored["payload"]["total_dollars"] = 0.0
    lines[1] = json.dumps(doctored, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = br.verify_chain(path, KEY)
    assert not report.ok and report.broken_at == 1
    assert "INVALID" in report.reason


def test_chain_break_on_deleted_line(tmp_path):
    path = tmp_path / "receipts.jsonl"
    for goal in (7, 9, 7):
        br.mint(_world(), goal, KEY, path=path)
    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[1]                                     # vanish the middle receipt
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = br.verify_chain(path, KEY)
    assert not report.ok and report.broken_at == 1
    assert "chain link" in report.reason


def test_chain_break_on_reordered_lines(tmp_path):
    path = tmp_path / "receipts.jsonl"
    for goal in (7, 9):
        br.mint(_world(), goal, KEY, path=path)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
    assert br.verify_chain(path, KEY).broken_at == 0


def test_empty_chain_is_ok(tmp_path):
    report = br.verify_chain(tmp_path / "absent.jsonl", KEY)
    assert report.ok and report.count == 0


def test_chain_file_mode_0600(tmp_path):
    import stat
    path = tmp_path / "receipts.jsonl"
    br.mint(_world(), 7, KEY, path=path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


# --- render -----------------------------------------------------------------

def test_render_human_readable(tmp_path):
    line = br.mint(_world(), 7, KEY, path=tmp_path / "r.jsonl")
    out = br.render(line)
    assert "goal=7" in out and "$2.0000" in out and "(genesis)" in out
    assert br.render("garbage") == "budget receipt: MALFORMED"


def test_goal_with_no_episodes_mints_zero_receipt(tmp_path):
    line = br.mint(FakeWorld([]), 42, KEY, path=tmp_path / "r.jsonl")
    payload = json.loads(line)["payload"]
    assert payload["total_dollars"] == 0
    assert payload["started_at"] is None and payload["ended_at"] is None
    assert br.verify(line, KEY) == br.VALID
