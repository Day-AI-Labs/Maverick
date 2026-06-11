"""Replay export to MP4 (roadmap: 2027 H2 UX).

A run's audit trail rendered as a watchable video: one captioned frame per
recorded step, timed by the gaps between events, encoded to an MP4 a reviewer
can scrub through without a Maverick install.

The work splits cleanly so the deterministic part is fully testable offline:

* **storyboard(goal_id)** — the pure core: the ordered list of
  ``Frame(index, kind, caption, seconds)`` with per-step durations derived
  from the event timestamps (clamped to a sane min/max). Secret- and
  PII-scrubbed via the same redactors :mod:`maverick.replay_export` uses, so
  nothing sensitive reaches a frame.
* **render(...)** — turns the storyboard into PNG frames (Pillow) and encodes
  them to MP4 via the existing ffmpeg tool (sandbox-mediated). Pillow/ffmpeg
  are optional: when absent, ``render`` still writes the **frame manifest +
  the exact ffmpeg command** so an operator can encode out-of-band. No new
  hard dependency on a video stack.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .replay_export import _iter_events_for_goal, _sanitize

log = logging.getLogger(__name__)

MIN_FRAME_SECONDS = 1.0
MAX_FRAME_SECONDS = 6.0
_DEFAULT_FPS = 25
_W, _H = 1280, 720


@dataclass(frozen=True)
class Frame:
    index: int
    kind: str
    caption: str
    seconds: float


def _event_ts(ev: dict) -> float | None:
    ts = ev.get("ts") or ev.get("created_at")
    try:
        return float(ts) if ts is not None else None
    except (TypeError, ValueError):
        return None


def _caption(ev: dict) -> str:
    body = {k: v for k, v in ev.items()
            if k not in ("kind", "event", "ts", "created_at", "goal_id",
                         "hash", "prev_hash", "sig", "key_id")}
    import json
    text = _sanitize(json.dumps(body, default=str))
    text = text.strip().strip("{}").strip()
    return text[:280]


def storyboard(goal_id: int, *, events: list[dict] | None = None) -> list[Frame]:
    """Ordered frames for a goal — the deterministic core (no rendering).

    Frame durations come from the wall-clock gap to the NEXT event, clamped
    to [MIN, MAX] seconds; the final frame gets the min duration. With no
    timestamps, every frame gets a uniform MIN duration.
    """
    evs = events if events is not None else list(_iter_events_for_goal(goal_id))
    frames: list[Frame] = []
    for i, ev in enumerate(evs):
        kind = str(ev.get("kind") or ev.get("event") or "?")
        nxt = evs[i + 1] if i + 1 < len(evs) else None
        secs = MIN_FRAME_SECONDS
        t0, t1 = _event_ts(ev), (_event_ts(nxt) if nxt else None)
        if t0 is not None and t1 is not None and t1 > t0:
            secs = max(MIN_FRAME_SECONDS, min(MAX_FRAME_SECONDS, t1 - t0))
        frames.append(Frame(index=i, kind=kind, caption=_caption(ev),
                            seconds=round(secs, 3)))
    return frames


def _ffmpeg_concat(frames: list[Frame], frame_dir: Path) -> str:
    """The ffconcat demuxer script: each PNG held for its frame duration."""
    lines = ["ffconcat version 1.0"]
    for f in frames:
        lines.append(f"file '{frame_dir / f'frame_{f.index:05d}.png'}'")
        lines.append(f"duration {f.seconds:g}")
    if frames:  # the demuxer needs the last file repeated to honor its duration
        lines.append(f"file '{frame_dir / f'frame_{frames[-1].index:05d}.png'}'")
    return "\n".join(lines) + "\n"


def ffmpeg_command(concat_path: Path, out_path: Path, *, fps: int = _DEFAULT_FPS) -> list[str]:
    """The exact argv to encode the concat script to MP4 (yuv420p, even dims)."""
    return [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-vsync", "vfr", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", str(out_path),
    ]


def _render_png(frame: Frame, path: Path) -> bool:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    img = Image.new("RGB", (_W, _H), (13, 17, 23))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, _W, 64], fill=(22, 27, 34))
    draw.text((24, 22), f"[{frame.index + 1}] {frame.kind}", fill=(63, 185, 80))
    # Wrap the caption to the canvas width (cheap fixed-width wrap).
    y = 110
    line = ""
    for word in frame.caption.split():
        if len(line) + len(word) + 1 > 84:
            draw.text((24, y), line, fill=(230, 237, 243))
            y += 28
            line = word
        else:
            line = f"{line} {word}".strip()
        if y > _H - 60:
            break
    if line and y <= _H - 60:
        draw.text((24, y), line, fill=(230, 237, 243))
    img.save(path, format="PNG")
    return True


@dataclass
class RenderResult:
    frames: int
    frame_dir: Path
    concat_path: Path
    command: list[str]
    encoded: bool
    detail: str


def render(goal_id: int, out_path: Path, *, sandbox=None,
           events: list[dict] | None = None, fps: int = _DEFAULT_FPS) -> RenderResult:
    """Render a goal's storyboard to MP4 (best-effort encode).

    Always writes the frame manifest (the ffconcat script) and computes the
    exact ffmpeg command. Renders PNG frames when Pillow is available and
    runs ffmpeg through ``sandbox`` (or the host ffmpeg) when present; when
    either is missing, ``encoded`` is False and the manifest + command are
    the deliverable for out-of-band encoding.
    """
    out_path = Path(out_path)
    frames = storyboard(goal_id, events=events)
    frame_dir = out_path.parent / f"{out_path.stem}_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    concat_path = frame_dir / "frames.ffconcat"
    concat_path.write_text(_ffmpeg_concat(frames, frame_dir), encoding="utf-8")
    command = ffmpeg_command(concat_path, out_path, fps=fps)

    if not frames:
        return RenderResult(0, frame_dir, concat_path, command, False,
                            "no events recorded for this goal")

    rendered = all(_render_png(f, frame_dir / f"frame_{f.index:05d}.png") for f in frames)
    if not rendered:
        return RenderResult(len(frames), frame_dir, concat_path, command, False,
                            "Pillow not installed; wrote frame manifest + ffmpeg "
                            "command for out-of-band encoding "
                            "(pip install 'maverick-agent[computer-use]')")

    try:
        from .tools import sandbox_run
        code, _out, err = sandbox_run(sandbox, command, timeout=300)
        if code == 0 and out_path.exists():
            return RenderResult(len(frames), frame_dir, concat_path, command, True,
                                f"encoded {len(frames)} frames -> {out_path}")
        return RenderResult(len(frames), frame_dir, concat_path, command, False,
                            f"ffmpeg failed (exit {code}): {str(err)[:160]}")
    except Exception as e:  # ffmpeg absent / sandbox error
        return RenderResult(len(frames), frame_dir, concat_path, command, False,
                            f"frames rendered; ffmpeg unavailable ({e}) — run the "
                            "command field to encode")


__all__ = ["Frame", "storyboard", "ffmpeg_command", "render", "RenderResult",
           "MIN_FRAME_SECONDS", "MAX_FRAME_SECONDS"]
