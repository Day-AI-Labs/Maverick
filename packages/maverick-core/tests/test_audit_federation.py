"""Federated audit-log verification: cross-node reciprocity over signed logs."""
from __future__ import annotations

from maverick.audit import federation as fed


def _sent(node, peer, corr):
    return {"node": node, "peer_node": peer, "correlation_id": corr,
            "direction": "sent", "kind": "delegate"}


def _recv(node, peer, corr):
    return {"node": node, "from_node": peer, "task_id": corr,
            "direction": "received", "kind": "accept"}


def test_extract_crossrefs_needs_peer_and_correlation():
    rows = [
        {"kind": "noise"},                                  # neither
        {"peer_node": "B"},                                 # no correlation
        {"correlation_id": "c1"},                           # no peer
        _sent("A", "B", "c1"),                              # a real reference
    ]
    refs = fed.extract_crossrefs("A", rows)
    assert len(refs) == 1
    assert refs[0].peer == "B" and refs[0].correlation == "c1"
    assert refs[0].direction == "sent"


def test_reciprocated_links_are_consistent():
    nodes = {
        "A": fed.NodeReport("A", True, crossrefs=fed.extract_crossrefs(
            "A", [_sent("A", "B", "c1")])),
        "B": fed.NodeReport("B", True, crossrefs=fed.extract_crossrefs(
            "B", [_recv("B", "A", "c1")])),
    }
    unrecip, untrusted = fed.cross_verify(nodes)
    assert unrecip == [] and untrusted == []


def test_dropped_half_is_unreciprocated():
    # A claims it delegated c1 to B, but B's log has no matching row.
    nodes = {
        "A": fed.NodeReport("A", True, crossrefs=fed.extract_crossrefs(
            "A", [_sent("A", "B", "c1")])),
        "B": fed.NodeReport("B", True, crossrefs=[]),  # B dropped its half
    }
    unrecip, untrusted = fed.cross_verify(nodes)
    assert len(unrecip) == 1
    assert unrecip[0].node == "A" and unrecip[0].peer == "B"
    assert untrusted == []


def test_direction_must_be_opposite():
    # both nodes recorded "sent" for the same correlation -> not a valid pair
    nodes = {
        "A": fed.NodeReport("A", True, crossrefs=fed.extract_crossrefs(
            "A", [_sent("A", "B", "c1")])),
        "B": fed.NodeReport("B", True, crossrefs=fed.extract_crossrefs(
            "B", [_sent("B", "A", "c1")])),
    }
    unrecip, _ = fed.cross_verify(nodes)
    assert len(unrecip) == 2  # neither half pairs with the other


def test_reference_into_broken_peer_is_untrusted():
    nodes = {
        "A": fed.NodeReport("A", True, crossrefs=fed.extract_crossrefs(
            "A", [_sent("A", "B", "c1")])),
        "B": fed.NodeReport("B", False, breaks=["broken"], crossrefs=[]),
    }
    unrecip, untrusted = fed.cross_verify(nodes)
    assert untrusted and untrusted[0].peer == "B"
    assert unrecip == []  # not counted as unreciprocated; peer can't be trusted


def test_reference_to_unknown_node_is_untrusted():
    nodes = {
        "A": fed.NodeReport("A", True, crossrefs=fed.extract_crossrefs(
            "A", [_sent("A", "ghost", "c1")])),
    }
    _unrecip, untrusted = fed.cross_verify(nodes)
    assert untrusted and untrusted[0].peer == "ghost"


def test_verify_federation_end_to_end(tmp_path):
    # No audit dirs on disk -> chain check is a no-op (intact); reciprocity
    # over the provided rows is what's exercised.
    inputs = {
        "A": (tmp_path / "a", [_sent("A", "B", "c1")]),
        "B": (tmp_path / "b", [_recv("B", "A", "c1")]),
    }
    report = fed.verify_federation(inputs)
    assert report.consistent is True
    assert set(report.nodes) == {"A", "B"}
    out = fed.render(report)
    assert "CONSISTENT" in out


def test_verify_federation_reports_inconsistency(tmp_path):
    inputs = {
        "A": (tmp_path / "a", [_sent("A", "B", "c1")]),
        "B": (tmp_path / "b", []),  # dropped half
    }
    report = fed.verify_federation(inputs)
    assert report.consistent is False
    assert len(report.unreciprocated) == 1
    assert "UNRECIPROCATED" in fed.render(report)


def test_collect_node_flags_broken_chain(tmp_path, monkeypatch):
    # A real (signed) day-file that fails verify_chain marks the node broken.
    audit = tmp_path / "node"
    audit.mkdir()
    (audit / "2026-01-01.ndjson").write_text(
        '{"hash": "x", "sig": "y", "prev_hash": ""}\n', encoding="utf-8")
    rep = fed.collect_node("A", audit, [])
    # crypto-less env yields a no_crypto break; either way the node is not intact
    assert rep.intact is False
