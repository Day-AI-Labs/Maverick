"""ffmpeg tool — common media operations via the local binary.

Auth: none. Requires the ``ffmpeg`` binary on PATH.

ops:
  - convert(input_path, output_path, args)        — generic transcode
  - extract_audio(input_path, output_path)
  - thumbnail(input_path, output_path, time, width)
  - info(input_path)                              — ffprobe stream summary

Mutations write to disk; we don't require ``confirm`` because the
sandbox already mediates write access.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_FFMPEG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["convert", "extract_audio", "thumbnail", "info"],
        },
        "input_path": {"type": "string"},
        "output_path": {"type": "string"},
        "args": {"type": "array", "items": {"type": "string"}},
        "time": {"type": "string", "description": "HH:MM:SS[.mmm] (thumbnail)."},
        "width": {"type": "integer"},
    },
    "required": ["op"],
}


def _need(bin_name: str) -> str | None:
    if shutil.which(bin_name):
        return None
    return f"ERROR: {bin_name} not on PATH. Install ffmpeg."


def _run_cmd(cmd: list[str], *, timeout: float = 600.0) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"TIMEOUT after {timeout}s"


def _op_convert(args: dict) -> str:
    err = _need("ffmpeg")
    if err:
        return err
    src = (args.get("input_path") or "").strip()
    dst = (args.get("output_path") or "").strip()
    if not src or not dst:
        return "ERROR: convert requires input_path and output_path"
    extra = [str(a) for a in (args.get("args") or [])]
    cmd = ["ffmpeg", "-y", "-i", src, *extra, dst]
    code, _out, stderr = _run_cmd(cmd, timeout=600)
    if code != 0:
        return f"ERROR: ffmpeg ({code}): {stderr.strip()[-500:]}"
    return f"wrote {dst}"


def _op_extract_audio(args: dict) -> str:
    err = _need("ffmpeg")
    if err:
        return err
    src = (args.get("input_path") or "").strip()
    dst = (args.get("output_path") or "").strip()
    if not src or not dst:
        return "ERROR: extract_audio requires input_path and output_path"
    code, _out, stderr = _run_cmd(
        ["ffmpeg", "-y", "-i", src, "-vn", "-acodec", "copy", dst],
        timeout=600,
    )
    if code != 0:
        # Fallback: re-encode to mp3 if -acodec copy fails (mismatched container).
        code2, _out, stderr2 = _run_cmd(
            ["ffmpeg", "-y", "-i", src, "-vn", "-b:a", "192k", dst],
            timeout=600,
        )
        if code2 != 0:
            return f"ERROR: extract_audio ({code2}): {stderr2.strip()[-500:]}"
    return f"wrote audio to {dst}"


def _op_thumbnail(args: dict) -> str:
    err = _need("ffmpeg")
    if err:
        return err
    src = (args.get("input_path") or "").strip()
    dst = (args.get("output_path") or "").strip()
    if not src or not dst:
        return "ERROR: thumbnail requires input_path and output_path"
    t = (args.get("time") or "00:00:01").strip()
    width = int(args.get("width") or 640)
    cmd = [
        "ffmpeg", "-y", "-ss", t, "-i", src,
        "-frames:v", "1", "-vf", f"scale={width}:-1", dst,
    ]
    code, _out, stderr = _run_cmd(cmd, timeout=120)
    if code != 0:
        return f"ERROR: thumbnail ({code}): {stderr.strip()[-300:]}"
    return f"wrote thumbnail to {dst}"


def _op_info(args: dict) -> str:
    err = _need("ffprobe")
    if err:
        return err
    src = (args.get("input_path") or "").strip()
    if not src:
        return "ERROR: info requires input_path"
    code, out, stderr = _run_cmd(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", src],
        timeout=30,
    )
    if code != 0:
        return f"ERROR: ffprobe ({code}): {stderr.strip()[-300:]}"
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return out[:3000]
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    lines = [
        f"format:    {fmt.get('format_name', '?')}",
        f"duration:  {fmt.get('duration', '?')}s",
        f"bitrate:   {fmt.get('bit_rate', '?')}",
        f"streams:   {len(streams)}",
    ]
    for s in streams:
        lines.append(
            f"  - {s.get('codec_type', '?'):>5} {s.get('codec_name', '?'):<8}  "
            f"{s.get('width', '')}x{s.get('height', '') or ''}  "
            f"{s.get('sample_rate', '')}"
        )
    return "\n".join(lines)


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    try:
        return {
            "convert":       _op_convert,
            "extract_audio": _op_extract_audio,
            "thumbnail":     _op_thumbnail,
            "info":          _op_info,
        }.get(op, lambda a: f"ERROR: unknown op {op!r}")(args)
    except Exception as e:
        return f"ERROR: ffmpeg request failed: {type(e).__name__}: {e}"


def ffmpeg_tool() -> Tool:
    return Tool(
        name="ffmpeg",
        description=(
            "Media operations via local ffmpeg + ffprobe. ops: "
            "convert (raw -i/-args wrapper), extract_audio, "
            "thumbnail (time + width), info (ffprobe JSON summary). "
            "Requires the ffmpeg binary on PATH."
        ),
        input_schema=_FFMPEG_SCHEMA,
        fn=_run,
    )
