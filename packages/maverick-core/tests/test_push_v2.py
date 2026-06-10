"""Push v2: device registry, priority floors, quiet hours, delivery ledger."""
from __future__ import annotations

from maverick.push_v2 import Device, PushRegistry


def _reg(tmp_path):
    return PushRegistry(path=tmp_path / "devices.json",
                        ledger_path=tmp_path / "ledger.json")


def _sender(log):
    def send(backend, body, title, priority):
        log.append((backend, priority))
        return 1
    return send


def test_register_route_record(tmp_path):
    reg = _reg(tmp_path)
    reg.register(Device("phone", "ntfy"))
    reg.register(Device("desktop", "slack"))
    sent: list = []
    out = reg.push("done", priority="default", hour=12,
                   send=_sender(sent), now=100.0)
    assert {o["device"] for o in out} == {"phone", "desktop"}
    assert all(o["ok"] for o in out)
    assert {b for b, _p in sent} == {"ntfy", "slack"}
    assert len(reg.deliveries()) == 2
    assert reg.deliveries(device="phone")[0]["backend"] == "ntfy"


def test_priority_floor(tmp_path):
    reg = _reg(tmp_path)
    reg.register(Device("phone", "ntfy", min_priority="high"))
    sent: list = []
    assert reg.push("meh", priority="default", hour=12, send=_sender(sent)) == []
    out = reg.push("important", priority="high", hour=12, send=_sender(sent))
    assert len(out) == 1


def test_quiet_hours_block_normal_but_not_urgent(tmp_path):
    reg = _reg(tmp_path)
    reg.register(Device("phone", "ntfy", quiet_hours=(22, 7)))
    sent: list = []
    # 23:00 is inside the overnight window
    assert reg.push("fyi", priority="default", hour=23, send=_sender(sent)) == []
    # urgent breaks through
    out = reg.push("fire", priority="urgent", hour=23, send=_sender(sent))
    assert len(out) == 1
    # 12:00 is outside the window
    assert len(reg.push("fyi", priority="default", hour=12,
                        send=_sender(sent))) == 1


def test_failed_send_recorded(tmp_path):
    reg = _reg(tmp_path)
    reg.register(Device("phone", "ntfy"))

    def boom(backend, body, title, priority):
        raise RuntimeError("network down")

    out = reg.push("x", hour=12, send=boom)
    assert out[0]["ok"] is False
    assert reg.deliveries()[0]["ok"] is False


def test_unregister(tmp_path):
    reg = _reg(tmp_path)
    reg.register(Device("phone", "ntfy"))
    assert reg.unregister("phone") is True
    assert reg.unregister("phone") is False
    assert reg.devices() == []


def test_ledger_bounded(tmp_path):
    import maverick.push_v2 as pv
    reg = _reg(tmp_path)
    reg.register(Device("phone", "ntfy"))
    sent: list = []
    for _ in range(pv._LEDGER_CAP + 50):
        reg.push("x", hour=12, send=_sender(sent))
    assert len(reg.deliveries()) == pv._LEDGER_CAP
