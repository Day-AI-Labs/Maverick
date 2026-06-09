"""3D model inspector tool (roadmap: 2027 H1 capabilities — "3D model viewer").

A headless "viewer": instead of rendering pixels, it parses a 3D mesh file and
reports the structural facts an agent actually reasons over — triangle/vertex
counts, the axis-aligned bounding box, and the model's dimensions — for STL
(ASCII and binary) and OBJ. Pure parsing, no GPU, no external lib.

ops:
  - inspect(path)  — summary stats for the mesh at ``path``.
"""
from __future__ import annotations

import os
import re
import struct
from typing import Any

from . import Tool

_MAX_BYTES = 80 * 1024 * 1024  # refuse absurd files


def _bbox(verts: list[tuple[float, float, float]]) -> str:
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    lo = (min(xs), min(ys), min(zs))
    hi = (max(xs), max(ys), max(zs))
    dim = tuple(round(hi[i] - lo[i], 4) for i in range(3))
    return (
        f"bbox_min: ({lo[0]:.4g}, {lo[1]:.4g}, {lo[2]:.4g})\n"
        f"bbox_max: ({hi[0]:.4g}, {hi[1]:.4g}, {hi[2]:.4g})\n"
        f"dimensions (w,h,d): ({dim[0]:g}, {dim[1]:g}, {dim[2]:g})"
    )


def _parse_obj(text: str) -> tuple[int, int, list[tuple[float, float, float]]]:
    verts: list[tuple[float, float, float]] = []
    faces = 0
    for line in text.splitlines():
        if line.startswith("v "):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
                except ValueError:
                    continue
        elif line.startswith("f "):
            faces += 1
    return len(verts), faces, verts


def _parse_ascii_stl(text: str) -> tuple[int, list[tuple[float, float, float]]]:
    verts: list[tuple[float, float, float]] = []
    facets = 0
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("vertex"):
            parts = s.split()
            if len(parts) >= 4:
                try:
                    verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
                except ValueError:
                    continue
        elif s.startswith("facet"):
            facets += 1
    return facets, verts


def _parse_binary_stl(data: bytes) -> tuple[int, list[tuple[float, float, float]]]:
    if len(data) < 84:
        return 0, []
    (count,) = struct.unpack_from("<I", data, 80)
    verts: list[tuple[float, float, float]] = []
    off = 84
    n = min(count, (len(data) - 84) // 50)
    for _ in range(n):
        # 12 floats: normal(3) + v1(3) + v2(3) + v3(3), then 2-byte attr.
        vals = struct.unpack_from("<12f", data, off)
        verts.extend([(vals[3], vals[4], vals[5]),
                      (vals[6], vals[7], vals[8]),
                      (vals[9], vals[10], vals[11])])
        off += 50
    return n, verts


def _inspect(path: str) -> str:
    size = os.path.getsize(path)
    if size > _MAX_BYTES:
        return f"ERROR: file too large ({size} bytes)"
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        data = f.read()

    if ext == ".obj":
        nv, nf, verts = _parse_obj(data.decode("utf-8", errors="replace"))
        if not verts:
            return "ERROR: no vertices found in OBJ"
        return f"format: OBJ\nvertices: {nv}\nfaces: {nf}\n{_bbox(verts)}"

    # STL: detect ASCII vs binary. ASCII starts with 'solid' AND contains 'facet'.
    head = data[:512].decode("ascii", errors="replace").lower()
    is_ascii = head.lstrip().startswith("solid") and "facet" in \
        data[:4096].decode("ascii", errors="replace").lower()
    if is_ascii:
        facets, verts = _parse_ascii_stl(data.decode("ascii", errors="replace"))
    else:
        facets, verts = _parse_binary_stl(data)
    if not verts:
        return "ERROR: no triangles found in STL"
    return (
        f"format: STL ({'ascii' if is_ascii else 'binary'})\n"
        f"triangles: {facets}\nvertices: {len(verts)}\n{_bbox(verts)}"
    )


def _run(args: dict[str, Any]) -> str:
    if args.get("op") not in (None, "inspect"):
        return f"ERROR: unknown op {args.get('op')!r}"
    path = (args.get("path") or "").strip()
    if not path:
        return "ERROR: path is required"
    if not os.path.isfile(path):
        return f"ERROR: no such file: {path}"
    if not re.search(r"\.(stl|obj)$", path, re.I):
        return "ERROR: only .stl and .obj are supported"
    try:
        return _inspect(path)
    except Exception as e:  # pragma: no cover - defensive
        return f"ERROR: parse failed: {type(e).__name__}: {e}"


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["inspect"]},
        "path": {"type": "string", "description": "path to a .stl or .obj mesh"},
    },
    "required": ["path"],
}


def model3d_inspect() -> Tool:
    return Tool(
        name="model3d_inspect",
        description=(
            "Inspect a 3D mesh file (.stl ASCII/binary, .obj) without a GPU: "
            "reports triangle/vertex counts, the axis-aligned bounding box, and "
            "the model's width/height/depth. op=inspect with a 'path'."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
