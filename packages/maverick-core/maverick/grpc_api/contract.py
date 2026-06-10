"""gRPC API v1 stability contract (roadmap: 2028 H2 ecosystem).

``maverick.proto`` (package ``maverick.v1``) is the external contract other
languages build against. "v1 stable" is a *guarantee*, and a guarantee needs
an enforcement mechanism: this module parses the proto into a structural
**inventory** — services, rpcs (with streaming-ness), messages, and every
field's ``(name, number, type, label)`` — and compares it against the
committed golden (``maverick_v1_contract.json``).

Stability rules (proto3 wire-compat):

* **Additive changes are allowed**: a new message, a new rpc, a new field with
  a previously-unused number.
* **Breaking changes fail**: removing/renaming a service, rpc, message, or
  field; changing a field's number or type; changing an rpc's
  request/response/streaming shape; reusing a removed field number.

``python -m maverick.grpc_api.contract --check`` is the CI gate;
``--regen`` rewrites the golden (a deliberate, reviewed act for additive
changes). The parser is a small line-grammar over the proto (no protoc
needed), so the gate runs in CI without grpcio.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PROTO_PATH = Path(__file__).with_name("maverick.proto")
GOLDEN_PATH = Path(__file__).with_name("maverick_v1_contract.json")

_SERVICE = re.compile(r"^\s*service\s+(\w+)\s*\{")
_RPC = re.compile(
    r"^\s*rpc\s+(\w+)\s*\(\s*(stream\s+)?([\w.]+)\s*\)\s*returns\s*"
    r"\(\s*(stream\s+)?([\w.]+)\s*\)")
_MESSAGE = re.compile(r"^\s*message\s+(\w+)\s*\{")
_FIELD = re.compile(
    r"^\s*(repeated\s+|optional\s+)?([\w.<>, ]+?)\s+(\w+)\s*=\s*(\d+)\s*;")
_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;")


def parse_inventory(proto_text: str) -> dict:
    """Parse a .proto into the structural inventory the contract pins."""
    inv: dict = {"package": "", "services": {}, "messages": {}}
    current_service: str | None = None
    current_message: str | None = None
    depth = 0
    for raw in proto_text.splitlines():
        line = raw.split("//", 1)[0]
        if not line.strip():
            continue
        m = _PACKAGE.match(line)
        if m:
            inv["package"] = m.group(1)
            continue
        m = _SERVICE.match(line)
        if m:
            current_service = m.group(1)
            inv["services"][current_service] = {}
            depth = 1
            continue
        m = _MESSAGE.match(line)
        if m:
            current_message = m.group(1)
            inv["messages"][current_message] = {}
            depth = 1
            continue
        if current_service:
            m = _RPC.match(line)
            if m:
                name, req_stream, req, resp_stream, resp = m.groups()
                inv["services"][current_service][name] = {
                    "request": req, "request_stream": bool(req_stream),
                    "response": resp, "response_stream": bool(resp_stream),
                }
        if current_message:
            m = _FIELD.match(line)
            if m:
                label, ftype, fname, fnum = m.groups()
                inv["messages"][current_message][fname] = {
                    "number": int(fnum),
                    "type": ftype.strip(),
                    "label": (label or "").strip(),
                }
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            current_service = None
            current_message = None
    return inv


def load_current() -> dict:
    return parse_inventory(PROTO_PATH.read_text(encoding="utf-8"))


def load_golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def breaking_changes(golden: dict, current: dict) -> list[str]:
    """Diffs that BREAK v1 wire/API compatibility ([] == compatible).

    Additions are fine; anything pinned in the golden must survive unchanged.
    """
    problems: list[str] = []
    if current.get("package") != golden.get("package"):
        problems.append(
            f"package changed: {golden.get('package')} -> {current.get('package')}")
    for svc, rpcs in golden.get("services", {}).items():
        cur_rpcs = current.get("services", {}).get(svc)
        if cur_rpcs is None:
            problems.append(f"service removed: {svc}")
            continue
        for rpc, shape in rpcs.items():
            cur = cur_rpcs.get(rpc)
            if cur is None:
                problems.append(f"rpc removed: {svc}.{rpc}")
            elif cur != shape:
                problems.append(f"rpc shape changed: {svc}.{rpc} {shape} -> {cur}")
    # field-number reuse needs the per-message set of golden numbers
    for msg, fields in golden.get("messages", {}).items():
        cur_fields = current.get("messages", {}).get(msg)
        if cur_fields is None:
            problems.append(f"message removed: {msg}")
            continue
        golden_numbers = {f["number"]: name for name, f in fields.items()}
        for fname, f in fields.items():
            cur = cur_fields.get(fname)
            if cur is None:
                problems.append(f"field removed: {msg}.{fname}")
            elif cur["number"] != f["number"]:
                problems.append(
                    f"field renumbered: {msg}.{fname} {f['number']} -> {cur['number']}")
            elif cur["type"] != f["type"] or cur["label"] != f["label"]:
                problems.append(
                    f"field type changed: {msg}.{fname} "
                    f"{f['label']} {f['type']} -> {cur['label']} {cur['type']}")
        for fname, cur in cur_fields.items():
            if fname in fields:
                continue
            owner = golden_numbers.get(cur["number"])
            if owner and owner != fname:
                problems.append(
                    f"field number reused: {msg}.{fname} takes {cur['number']} "
                    f"which belonged to {msg}.{owner}")
    return problems


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- CLI shell
    import argparse
    p = argparse.ArgumentParser(prog="maverick.grpc_api.contract",
                                description="gRPC API v1 stability gate.")
    p.add_argument("--check", action="store_true", help="fail on breaking changes")
    p.add_argument("--regen", action="store_true",
                   help="rewrite the golden from the current proto (reviewed act)")
    args = p.parse_args(argv)
    current = load_current()
    if args.regen:
        GOLDEN_PATH.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
        print(f"golden regenerated: {GOLDEN_PATH.name}")
        return 0
    problems = breaking_changes(load_golden(), current)
    if problems:
        print("gRPC API v1 contract BROKEN:")
        for prob in problems:
            print(f"  {prob}")
        return 1 if args.check else 0
    print("gRPC API v1 contract: compatible")
    return 0


__all__ = ["parse_inventory", "load_current", "load_golden", "breaking_changes",
           "PROTO_PATH", "GOLDEN_PATH"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
