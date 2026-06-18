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

from ..safety.action_evidence import seal_bracketed
from ..safety.action_gate import computer_action_risk, gate_computer_action
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


def _maybe_seal_capture(b64: str) -> None:
    """Persist + seal a screenshot when a sealing key is configured.

    Captures land under ``data_dir("captures")/<utc-stamp>.png`` and each is
    appended to the directory's tamper-evident ledger
    (:mod:`maverick.screenshot_seal`). Opt-in purely by key presence
    ([safety] screenshot_key / MAVERICK_SCREENSHOT_KEY); best-effort -- a
    sealing problem must never break the screenshot the model is waiting on.
    """
    try:
        from ..screenshot_seal import SealKeyMissing, _key, seal
        try:
            _key(None)  # probe FIRST: no key -> no capture dir, no file
        except SealKeyMissing:
            return  # sealing is off; capture stays in-memory only
        from datetime import datetime, timezone

        from ..paths import data_dir
        captures = data_dir("captures")
        captures.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        path = captures / f"{stamp}.png"
        path.write_bytes(base64.b64decode(b64))
        seal(path)
    except Exception:  # pragma: no cover -- evidence capture is best-effort
        log.debug("screenshot seal failed", exc_info=True)


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


def _do_screenshot() -> str:
    """Grab + (optionally) seal + OCR a screenshot. Returns the tool_result
    string or an ``ERROR:`` string if capture deps are missing."""
    try:
        b64 = _screenshot_png_b64()
    except ImportError as e:
        return f"ERROR: {e}"
    log.info("computer.screenshot len=%d", len(b64))
    # Tamper-evident capture (opt-in by key presence): persist the PNG and
    # seal it into the hash-chained ledger so it's usable as evidence.
    # No key configured -> no seal, behavior unchanged.
    _maybe_seal_capture(b64)
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


def _do_cursor_position(pyautogui, coord, args: dict[str, Any]) -> str:
    x, y = pyautogui.position()
    log.info("computer.cursor_position -> (%d, %d)", x, y)
    return f"({x}, {y})"


def _do_wait(pyautogui, coord, args: dict[str, Any]) -> str:
    duration = float(args.get("duration") or 1.0)
    duration = max(0.0, min(duration, 30.0))  # cap at 30s
    time.sleep(duration)
    log.info("computer.wait %.1fs", duration)
    return f"waited {duration:.1f}s"


def _do_mouse_move(pyautogui, coord, args: dict[str, Any]) -> str:
    if not coord:
        return "ERROR: mouse_move requires coordinate=[x, y]"
    pyautogui.moveTo(coord[0], coord[1], duration=0.05)
    log.info("computer.mouse_move -> %s", coord)
    return f"moved to {coord}"


def _do_left_click(pyautogui, coord, args: dict[str, Any]) -> str:
    if coord:
        pyautogui.click(coord[0], coord[1])
    else:
        pyautogui.click()
    log.info("computer.left_click at %s", coord or pyautogui.position())
    return f"clicked at {coord or pyautogui.position()}"


def _do_right_click(pyautogui, coord, args: dict[str, Any]) -> str:
    if coord:
        pyautogui.rightClick(coord[0], coord[1])
    else:
        pyautogui.rightClick()
    log.info("computer.right_click at %s", coord or pyautogui.position())
    return f"right-clicked at {coord or pyautogui.position()}"


def _do_middle_click(pyautogui, coord, args: dict[str, Any]) -> str:
    if coord:
        pyautogui.middleClick(coord[0], coord[1])
    else:
        pyautogui.middleClick()
    log.info("computer.middle_click at %s", coord or pyautogui.position())
    return f"middle-clicked at {coord or pyautogui.position()}"


def _do_double_click(pyautogui, coord, args: dict[str, Any]) -> str:
    if coord:
        pyautogui.doubleClick(coord[0], coord[1])
    else:
        pyautogui.doubleClick()
    log.info("computer.double_click at %s", coord or pyautogui.position())
    return f"double-clicked at {coord or pyautogui.position()}"


def _do_left_click_drag(pyautogui, coord, args: dict[str, Any]) -> str:
    if not coord:
        return "ERROR: left_click_drag requires coordinate=[x, y] (target)"
    duration = float(args.get("duration") or 0.5)
    pyautogui.dragTo(coord[0], coord[1], duration=duration, button="left")
    log.info("computer.drag -> %s (duration=%.1fs)", coord, duration)
    return f"dragged to {coord}"


def _do_type(pyautogui, coord, args: dict[str, Any]) -> str:
    text = args.get("text") or ""
    if not text:
        return "ERROR: type requires text"
    # ~50 wpm typing -- realistic enough to not trigger paste-detection
    # in apps that have it, while still being fast.
    pyautogui.typewrite(text, interval=0.02)
    log.info("computer.type len=%d", len(text))
    return f"typed {len(text)} chars"


def _do_key(pyautogui, coord, args: dict[str, Any]) -> str:
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


def _do_scroll(pyautogui, coord, args: dict[str, Any]) -> str:
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


# action -> handler(pyautogui, coord, args) -> str. These run AFTER pyautogui
# is imported and the coordinate is clamped, so each handler can stay flat.
_PYAUTOGUI_ACTIONS = {
    "cursor_position": _do_cursor_position,
    "wait": _do_wait,
    "mouse_move": _do_mouse_move,
    "left_click": _do_left_click,
    "right_click": _do_right_click,
    "middle_click": _do_middle_click,
    "double_click": _do_double_click,
    "left_click_drag": _do_left_click_drag,
    "type": _do_type,
    "key": _do_key,
    "scroll": _do_scroll,
}


def _run_computer_action(args: dict[str, Any]) -> str:
    if os.environ.get("MAVERICK_COMPUTER_DISABLE") == "1":
        return "ERROR: computer-use tool disabled by MAVERICK_COMPUTER_DISABLE=1"
    action = args.get("action")
    if not action:
        return "ERROR: action is required"
    # Reject unknown actions BEFORE trying to import pyautogui so callers
    # validating the schema get a clear error even without optional deps.
    if action not in _VALID_ACTIONS:
        return f"ERROR: unknown action {action!r}"

    # Per-action approval gate (mutating actuations only -- clicks/keystrokes/
    # drag). No-op in the default auto-approve consent mode; routes the action
    # through the approval queue / TTY prompt when an operator turns gating on
    # (or enterprise mode flips the default to 'ask'). Read-only actions
    # (screenshot/cursor_position/wait/mouse_move/scroll) are never gated.
    denied = gate_computer_action(action, args)
    if denied is not None:
        return denied

    # Screenshot is the most common action; handle separately (doesn't
    # need pyautogui, just mss).
    if action == "screenshot":
        return _do_screenshot()

    # Return an error STRING (like the screenshot path above), not a raised
    # ImportError: the tool fn contract is ``-> str``, and a raised exception
    # crashed direct callers and was inconsistent with the browser tool
    # (user-testing finding).
    try:
        pyautogui = _ensure_pyautogui()
    except ImportError as e:
        return f"ERROR: {e}"
    pyautogui.FAILSAFE = False  # Don't crash on corner-of-screen mouse moves.

    # cursor_position and wait don't need a coordinate; everything else may.
    coord = None
    if action not in ("cursor_position", "wait"):
        coord = _clamp_coordinate(pyautogui, args.get("coordinate"))

    handler = _PYAUTOGUI_ACTIONS.get(action)
    if handler is not None:
        if computer_action_risk(action, args) == "high":
            # Bracket a high-risk actuation with sealed before/after captures
            # (no-op unless screenshot sealing is configured).
            return seal_bracketed(
                _screenshot_png_b64,
                lambda: handler(pyautogui, coord, args),
                action=f"computer.{action}",
            )
        return handler(pyautogui, coord, args)

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
