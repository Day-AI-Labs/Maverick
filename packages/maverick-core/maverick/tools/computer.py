"""Computer-use tool. Matches Anthropic's ``computer_20250124`` spec.

Lets the agent see the screen and drive mouse/keyboard. Implemented via
pyautogui for cross-platform input + mss for fast screenshots. Both
ship as the ``[computer-use]`` extra; the tool factory raises an
ImportError with an actionable message if they're not installed.

When this tool is registered, the agent kernel passes it through to
Claude 4.x as a native computer_20250124 tool, which means the model
emits structured actions (action='screenshot', action='mouse_move',
coordinate=[x,y], etc.) and we execute them.

Safety:
  - Each invocation is logged with action + coordinates so users can
    audit what the agent did.
  - The agent kernel runs this through the same Shield checks as other
    tools, so blocked-tool-call rules apply.
  - Coordinates clamped to the active display's bounds.
  - ``MAVERICK_COMPUTER_DISABLE=1`` env var disables the tool entirely
    (kill switch for production deployments where the user wants the
    agent capability but not actual mouse control).
"""
from __future__ import annotations

import base64
import io
import logging
import os
import tempfile
import time
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_COMPUTER_USE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "key", "type", "mouse_move", "left_click", "left_click_drag",
                "right_click", "middle_click", "double_click", "screenshot",
                "cursor_position", "scroll", "wait",
            ],
            "description": "The action to perform.",
        },
        "coordinate": {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 2, "maxItems": 2,
            "description": "[x, y] pixel coords. Required for *_click and mouse_move.",
        },
        "text": {
            "type": "string",
            "description": "Text to type (for 'type' action) or key/chord (for 'key').",
        },
        "scroll_direction": {
            "type": "string",
            "enum": ["up", "down", "left", "right"],
        },
        "scroll_amount": {
            "type": "integer",
            "description": "Notch count for 'scroll' (default 3).",
        },
        "duration": {
            "type": "number",
            "description": "Seconds for 'wait' or drag duration.",
        },
    },
    "required": ["action"],
}


def _ensure_pyautogui():
    try:
        import pyautogui  # noqa
    except ImportError as e:
        raise ImportError(
            "pyautogui not installed. Run: pip install 'maverick-agent[computer-use]'"
        ) from e
    return __import__("pyautogui")


def _screenshot_png_b64() -> str:
    """Grab the primary display and return base64-encoded PNG."""
    try:
        import mss
        from PIL import Image
    except ImportError as e:
        raise ImportError(
            "mss + pillow not installed. Run: pip install 'maverick-agent[computer-use]'"
        ) from e
    with mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.rgb)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")


def _ocr_enabled() -> bool:
    return os.environ.get("MAVERICK_COMPUTER_OCR", "").lower() in (
        "1", "true", "yes", "on",
    )


def _ocr_png_b64(b64: str) -> str:
    """Best-effort OCR of a base64 PNG via sandboxed tesseract.

    Returns "" on ANY failure (bad base64, tesseract missing, timeout, or
    subprocess error). OCR is a fallback for when the model can't see a DOM /
    accessibility tree, never a hard requirement.
    """
    tmp_path = ""
    try:
        from . import sandbox_run

        png = base64.b64decode(b64)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(png)
            tmp_path = tmp.name

        code, out, stderr = sandbox_run(
            None, ["tesseract", tmp_path, "-", "-l", "eng", "--psm", "3"], timeout=120,
        )
        if code != 0:
            log.debug(
                "computer-use OCR tesseract failed (%s): %s",
                code, (stderr or "").strip()[:300],
            )
            return ""
        return (out or "").strip()
    except Exception as e:  # pragma: no cover - fail-open
        log.debug("computer-use OCR unavailable: %s", e)
        return ""
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _clamp_coordinate(pyautogui, coord: list | None) -> tuple[int, int] | None:
    if not coord:
        return None
    if len(coord) != 2:
        raise ValueError(f"coordinate must be [x, y]; got {coord!r}")
    w, h = pyautogui.size()
    x = max(0, min(int(coord[0]), w - 1))
    y = max(0, min(int(coord[1]), h - 1))
    return (x, y)


_VALID_ACTIONS = frozenset({
    "key", "type", "mouse_move", "left_click", "left_click_drag",
    "right_click", "middle_click", "double_click", "screenshot",
    "cursor_position", "scroll", "wait",
})


def _run_computer_action(args: dict[str, Any]) -> str:  # noqa: C901
    if os.environ.get("MAVERICK_COMPUTER_DISABLE") == "1":
        return "ERROR: computer-use tool disabled by MAVERICK_COMPUTER_DISABLE=1"
    action = args.get("action")
    if not action:
        return "ERROR: action is required"
    # Reject unknown actions BEFORE trying to import pyautogui so callers
    # validating the schema get a clear error even without optional deps.
    if action not in _VALID_ACTIONS:
        return f"ERROR: unknown action {action!r}"

    # Screenshot is the most common action; handle separately (doesn't
    # need pyautogui, just mss).
    if action == "screenshot":
        try:
            b64 = _screenshot_png_b64()
        except ImportError as e:
            return f"ERROR: {e}"
        log.info("computer.screenshot len=%d", len(b64))
        # Claude expects the screenshot as a tool_result image block.
        # The agent kernel translates this string back into a block.
        out = f"<screenshot mime=image/png base64>{b64}</screenshot>"
        # Optional OCR fallback (MAVERICK_COMPUTER_OCR=1): attach recognized
        # text next to the image for models/situations without a DOM. No-op
        # if OCR deps are absent.
        if _ocr_enabled():
            text = _ocr_png_b64(b64)
            if text:
                out += f"\n<ocr>{text}</ocr>"
        return out

    pyautogui = _ensure_pyautogui()
    pyautogui.FAILSAFE = False  # Don't crash on corner-of-screen mouse moves.

    if action == "cursor_position":
        x, y = pyautogui.position()
        log.info("computer.cursor_position -> (%d, %d)", x, y)
        return f"({x}, {y})"

    if action == "wait":
        duration = float(args.get("duration") or 1.0)
        duration = max(0.0, min(duration, 30.0))  # cap at 30s
        time.sleep(duration)
        log.info("computer.wait %.1fs", duration)
        return f"waited {duration:.1f}s"

    coord = _clamp_coordinate(pyautogui, args.get("coordinate"))

    if action == "mouse_move":
        if not coord:
            return "ERROR: mouse_move requires coordinate=[x, y]"
        pyautogui.moveTo(coord[0], coord[1], duration=0.05)
        log.info("computer.mouse_move -> %s", coord)
        return f"moved to {coord}"

    if action == "left_click":
        if coord:
            pyautogui.click(coord[0], coord[1])
        else:
            pyautogui.click()
        log.info("computer.left_click at %s", coord or pyautogui.position())
        return f"clicked at {coord or pyautogui.position()}"

    if action == "right_click":
        if coord:
            pyautogui.rightClick(coord[0], coord[1])
        else:
            pyautogui.rightClick()
        log.info("computer.right_click at %s", coord or pyautogui.position())
        return f"right-clicked at {coord or pyautogui.position()}"

    if action == "middle_click":
        if coord:
            pyautogui.middleClick(coord[0], coord[1])
        else:
            pyautogui.middleClick()
        log.info("computer.middle_click at %s", coord or pyautogui.position())
        return f"middle-clicked at {coord or pyautogui.position()}"

    if action == "double_click":
        if coord:
            pyautogui.doubleClick(coord[0], coord[1])
        else:
            pyautogui.doubleClick()
        log.info("computer.double_click at %s", coord or pyautogui.position())
        return f"double-clicked at {coord or pyautogui.position()}"

    if action == "left_click_drag":
        if not coord:
            return "ERROR: left_click_drag requires coordinate=[x, y] (target)"
        duration = float(args.get("duration") or 0.5)
        pyautogui.dragTo(coord[0], coord[1], duration=duration, button="left")
        log.info("computer.drag -> %s (duration=%.1fs)", coord, duration)
        return f"dragged to {coord}"

    if action == "type":
        text = args.get("text") or ""
        if not text:
            return "ERROR: type requires text"
        # ~50 wpm typing -- realistic enough to not trigger paste-detection
        # in apps that have it, while still being fast.
        pyautogui.typewrite(text, interval=0.02)
        log.info("computer.type len=%d", len(text))
        return f"typed {len(text)} chars"

    if action == "key":
        text = args.get("text") or ""
        if not text:
            return "ERROR: key requires text (e.g. 'ctrl+c', 'Return', 'shift+tab')"
        # Anthropic spec uses xdotool-style ('ctrl+c'); pyautogui uses
        # hotkey('ctrl', 'c'). Convert here.
        keys = [k.strip().lower() for k in text.replace("-", "+").split("+") if k.strip()]
        # Normalise common synonyms.
        norm_map = {
            "return": "enter", "escape": "esc", "del": "delete",
            "back_space": "backspace", "page_up": "pageup", "page_down": "pagedown",
        }
        keys = [norm_map.get(k, k) for k in keys]
        pyautogui.hotkey(*keys)
        log.info("computer.key %s", "+".join(keys))
        return f"pressed {'+'.join(keys)}"

    if action == "scroll":
        direction = args.get("scroll_direction") or "down"
        amount = int(args.get("scroll_amount") or 3)
        # pyautogui.scroll: positive=up, negative=down. Horizontal uses
        # hscroll -- the old map sent delta 0 for left/right, so the scroll was
        # a silent no-op while the tool reported success.
        if coord:
            pyautogui.moveTo(coord[0], coord[1])
        if direction in ("up", "down"):
            pyautogui.scroll(amount if direction == "up" else -amount)
        else:
            pyautogui.hscroll(-amount if direction == "left" else amount)
        log.info("computer.scroll %s %d", direction, amount)
        return f"scrolled {direction} {amount}"

    # Defense in depth -- _VALID_ACTIONS guard at the top should make
    # this unreachable.
    return f"ERROR: unknown action {action!r}"


def computer() -> Tool:
    """Factory: builds the computer-use tool.

    The tool name matches Anthropic's expected ``computer`` for the
    native ``computer_20250124`` type. The description points the
    agent at what's available.
    """
    return Tool(
        name="computer",
        description=(
            "Drive the computer's display, mouse, and keyboard. "
            "Use screenshot to see the screen; mouse_move + left_click "
            "to interact; type/key to enter text. Coordinates are pixels "
            "from the top-left of the primary display."
        ),
        input_schema=_COMPUTER_USE_INPUT_SCHEMA,
        fn=_run_computer_action,
    )
