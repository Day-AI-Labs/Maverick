"""Tests for the per-action approval gate (computer + browser tools)."""
from __future__ import annotations

import pytest
from maverick.safety import action_gate
from maverick.safety.consent import ConsentDecision


@pytest.fixture(autouse=True)
def _clean_mode(tmp_path, monkeypatch):
    # Keep any audit/ledger side effects inside tmp and start from the default
    # (unset) consent mode unless a test overrides it.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_CONSENT_MODE", raising=False)


def _capture(monkeypatch):
    """Replace require_consent with a recorder that always grants."""
    calls: list[dict] = []

    def fake(name, *, risk, scope, detail, provenance, raise_on_deny=False):
        calls.append(
            {"name": name, "risk": risk, "scope": scope,
             "detail": detail, "provenance": provenance},
        )
        return ConsentDecision(True, "auto", risk, 0.0)

    monkeypatch.setattr(action_gate, "require_consent", fake)
    return calls


# --- non-mutating actions are never gated -----------------------------------

@pytest.mark.parametrize(
    "action",
    ["screenshot", "cursor_position", "wait", "mouse_move", "scroll", "bogus"],
)
def test_computer_nonmutating_never_gated(action, monkeypatch):
    calls = _capture(monkeypatch)
    assert action_gate.gate_computer_action(action, {}) is None
    assert calls == []


@pytest.mark.parametrize(
    "action",
    ["current_url", "screenshot", "extract_text", "extract_html", "find_text",
     "wait_for", "list_links", "save_session", "go_back", "go_forward",
     "close", "bogus"],
)
def test_browser_nonmutating_never_gated(action, monkeypatch):
    calls = _capture(monkeypatch)
    assert action_gate.gate_browser_action(action, {}) is None
    assert calls == []


# --- default auto-approve = no behavior change; auto-deny blocks -------------

def test_default_auto_approve_allows():
    # Real consent path (default mode) -> granted -> None (proceed).
    assert action_gate.gate_computer_action("left_click", {"coordinate": [10, 20]}) is None
    assert action_gate.gate_browser_action("click", {"selector": "#ok"}) is None


def test_auto_deny_blocks_with_error(monkeypatch):
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-deny")
    out = action_gate.gate_computer_action("left_click", {"coordinate": [1, 2]})
    assert out is not None and out.startswith("ERROR:")
    assert "denied by approval gate" in out

    out2 = action_gate.gate_browser_action("click", {"selector": "#x"})
    assert out2 is not None and out2.startswith("ERROR:")


# --- risk classification -----------------------------------------------------

def test_browser_click_pay_is_high(monkeypatch):
    calls = _capture(monkeypatch)
    action_gate.gate_browser_action("click", {"selector": "text=Pay now"})
    assert calls[0]["risk"] == "high"
    assert calls[0]["name"] == "browser.click"
    assert calls[0]["provenance"] == "browser.click"


def test_browser_click_ordinary_is_medium(monkeypatch):
    calls = _capture(monkeypatch)
    action_gate.gate_browser_action("click", {"selector": "#search-box"})
    assert calls[0]["risk"] == "medium"


def test_computer_key_return_is_high(monkeypatch):
    calls = _capture(monkeypatch)
    action_gate.gate_computer_action("key", {"text": "Return"})
    assert calls[0]["risk"] == "high"


def test_computer_ordinary_click_is_medium(monkeypatch):
    calls = _capture(monkeypatch)
    action_gate.gate_computer_action("left_click", {"coordinate": [5, 5]})
    assert calls[0]["risk"] == "medium"


def test_fill_form_values_scanned_for_risk(monkeypatch):
    calls = _capture(monkeypatch)
    action_gate.gate_browser_action("fill_form", {"fields": {"#note": "wire transfer"}})
    assert calls[0]["risk"] == "high"


# --- privacy: typed values never appear in the audit scope/detail ------------

def test_browser_typed_value_not_in_detail(monkeypatch):
    calls = _capture(monkeypatch)
    secret = "hunter2-SECRET"  # pragma: allowlist secret
    action_gate.gate_browser_action("type", {"selector": "#pw", "text": secret})
    blob = f"{calls[0]['detail']} {calls[0]['scope']}"
    assert secret not in blob
    assert str(len(secret)) in calls[0]["detail"]  # length is logged instead


def test_computer_typed_value_not_in_detail(monkeypatch):
    calls = _capture(monkeypatch)
    action_gate.gate_computer_action("type", {"text": "topsecret"})
    assert "topsecret" not in f"{calls[0]['detail']} {calls[0]['scope']}"


def test_fill_form_values_not_in_detail(monkeypatch):
    calls = _capture(monkeypatch)
    action_gate.gate_browser_action(
        "fill_form", {"fields": {"#iban": "DE89370400440532013000"}},
    )
    assert "DE89370400440532013000" not in f"{calls[0]['detail']} {calls[0]['scope']}"
    assert "#iban" in calls[0]["detail"]  # selector is shown, value is not
