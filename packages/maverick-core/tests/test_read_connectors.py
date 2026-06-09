"""Read-only connector bridge: a GET-only variant of a vendor connector
that a trusted finance pack can reach -- closing the pack<->connector gap
surfaced in test_fleet_spine, without handing that seat write capability.
Reference slice: modern_treasury_read -> finance_treasury / finance_cashflow."""
from __future__ import annotations

from maverick.capability import Capability
from maverick.domain import builtin_dir, domain_capability, load_domains
from maverick.safety.tool_risk import tool_risk
from maverick.tools.enterprise_connectors import (
    ENTERPRISE_CONNECTOR_NAMES,
    READ_CONNECTOR_NAMES,
    enterprise_connectors,
)


def _tools() -> dict:
    return {t.name: t for t in enterprise_connectors()}


def test_sensitive_read_connector_is_registered_high_and_get_only():
    tools = _tools()
    assert "modern_treasury_read" in tools
    assert "modern_treasury_read" in READ_CONNECTOR_NAMES
    # GET-only still carries sensitive banking data, so it fails closed to high
    # unless an operator explicitly relaxes it for a trusted deployment.
    assert tool_risk("modern_treasury_read") == "high"
    assert "modern_treasury_read" not in ENTERPRISE_CONNECTOR_NAMES
    # GET-only schema (the model can't even express a write)
    assert tools["modern_treasury_read"].input_schema["properties"]["op"]["enum"] == ["get"]


def test_read_connector_refuses_writes_while_the_write_seat_stays_high():
    fn = _tools()["modern_treasury_read"].fn
    for op in ("post", "put", "patch", "delete"):
        out = fn({"op": op, "path": "/api/payment_orders", "confirm": True})
        assert "read-only" in out, f"{op} should be refused by the read seat"
        assert "DRY RUN" not in out  # refused outright, not just write-gated
    # the paired write connector keeps full capability and stays high-risk
    assert tool_risk("modern_treasury") == "high"


def test_treasury_packs_can_now_reach_the_executable_read_seat():
    parent = Capability(principal="agent:finance_controller-0", max_risk="high")
    for pack in ("finance_treasury", "finance_cashflow"):
        prof = load_domains(builtin_dir())[pack]
        cap = domain_capability(prof, parent, f"agent:{pack}-1")
        # the sensitive read seat is reachable because the trusted pack explicitly
        # allows it and carries a high-risk ceiling...
        assert cap.permits("modern_treasury_read"), pack
        # ...while the write connector is dropped and the money seal holds
        assert not cap.permits("modern_treasury"), pack
        assert not cap.permits("wire_transfer"), pack
