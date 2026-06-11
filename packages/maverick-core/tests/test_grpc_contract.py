"""gRPC API v1 stability contract: parser + golden compat gate."""
from __future__ import annotations

from maverick.grpc_api import contract

_PROTO = """
syntax = "proto3";
package maverick.v1;
service Maverick {
  rpc StartGoal(StartGoalRequest) returns (StartGoalResponse);
  rpc StreamEpisode(StreamEpisodeRequest) returns (stream Event);
}
message StartGoalRequest {
  string title = 1;
  double max_dollars = 3;
  repeated string tags = 4;
}
message Event {
  int64 id = 1;
}
"""


def test_parser_inventory_shape():
    inv = contract.parse_inventory(_PROTO)
    assert inv["package"] == "maverick.v1"
    assert inv["services"]["Maverick"]["StreamEpisode"]["response_stream"] is True
    assert inv["services"]["Maverick"]["StartGoal"]["response_stream"] is False
    f = inv["messages"]["StartGoalRequest"]["tags"]
    assert f == {"number": 4, "type": "string", "label": "repeated"}


def test_real_proto_matches_committed_golden():
    """The CI gate: the shipped proto must satisfy its own golden."""
    assert contract.breaking_changes(contract.load_golden(),
                                     contract.load_current()) == []


def test_golden_pins_the_known_v1_surface():
    g = contract.load_golden()
    assert g["package"] == "maverick.v1"
    assert "StartGoal" in g["services"]["Maverick"]
    assert "RunGoal" in g["services"]["Maverick"]
    assert g["messages"]["StartGoalRequest"]["title"]["number"] == 1


def _mutate(**kw):
    golden = contract.parse_inventory(_PROTO)
    current = contract.parse_inventory(kw.get("proto", _PROTO))
    return contract.breaking_changes(golden, current)


def test_additive_changes_allowed():
    added = _PROTO + "\nmessage NewThing { string x = 1; }\n"
    assert _mutate(proto=added) == []
    new_field = _PROTO.replace("repeated string tags = 4;",
                               "repeated string tags = 4;\n  string note = 5;")
    assert _mutate(proto=new_field) == []


def test_field_removal_breaks():
    removed = _PROTO.replace("  double max_dollars = 3;\n", "")
    assert any("field removed: StartGoalRequest.max_dollars" in p
               for p in _mutate(proto=removed))


def test_field_renumber_breaks():
    renum = _PROTO.replace("double max_dollars = 3;", "double max_dollars = 9;")
    assert any("renumbered" in p for p in _mutate(proto=renum))


def test_field_type_change_breaks():
    retyped = _PROTO.replace("double max_dollars = 3;", "int64 max_dollars = 3;")
    assert any("type changed" in p for p in _mutate(proto=retyped))


def test_rpc_shape_change_breaks():
    unstreamed = _PROTO.replace("returns (stream Event)", "returns (Event)")
    assert any("rpc shape changed" in p for p in _mutate(proto=unstreamed))


def test_rpc_and_service_removal_break():
    no_rpc = _PROTO.replace(
        "  rpc StartGoal(StartGoalRequest) returns (StartGoalResponse);\n", "")
    assert any("rpc removed" in p for p in _mutate(proto=no_rpc))
    no_svc = _PROTO.replace("service Maverick", "service Other")
    assert any("service removed" in p for p in _mutate(proto=no_svc))


def test_field_number_reuse_breaks():
    reused = _PROTO.replace("  double max_dollars = 3;\n", "")\
                   .replace("repeated string tags = 4;",
                            "repeated string tags = 4;\n  string sneaky = 3;")
    problems = _mutate(proto=reused)
    assert any("field number reused" in p and "sneaky" in p for p in problems)


def test_package_change_breaks():
    v2 = _PROTO.replace("package maverick.v1;", "package maverick.v2;")
    assert any("package changed" in p for p in _mutate(proto=v2))
