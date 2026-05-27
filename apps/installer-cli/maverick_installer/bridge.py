"""Python sidecar for the Tauri desktop installer.

Reads wizard steps from stdin, writes JSON-formatted next-step
descriptors to stdout. The Tauri Rust shell drives this process and
the Svelte UI sends user answers via Tauri invoke calls.

Protocol (line-delimited JSON):

  stdin:  <user_answer_string>  (empty string for first call)
  stdout: {"id": "<step_id>", "question": "...", "choices": ["...", ...]}

When the wizard is complete, sidecar emits ``{"id": "__done__", ...}``
and exits.

This script is a thin layer over ``maverick_installer.wizard`` so the
GUI and CLI stay in lockstep -- one wizard implementation, two front
ends.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from . import models as catalog
from .wizard import (
    CHANNELS,
    CONFIG_DIR,
    write_config,
)


def _step(id: str, question: str, choices: list[str]) -> dict[str, Any]:
    return {"id": id, "question": question, "choices": choices}


def _send(step: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(step) + "\n")
    sys.stdout.flush()


def _recv() -> str:
    return sys.stdin.readline().strip()


STEPS = [
    "welcome",
    "deployment",
    "providers",
    "models_default",
    "channels_pick",
    "safety",
    "confirm",
]


def run() -> None:
    """Sidecar entry point.

    Simplified linear flow vs. the CLI wizard's branching; the desktop
    installer is opinionated for non-technical users -- it picks sensible
    defaults and asks fewer questions.
    """
    state: dict[str, Any] = {
        "deployment": "desktop",
        "providers": ["anthropic"],
        "role_models": {},
        "channels": {},
        "channel_envs": set(),
        "safety": {
            "profile": "balanced", "block_threshold": "high",
            "scan_input": True, "scan_tool_calls": True, "scan_output": True,
        },
        "budget": {"max_dollars": 5.0, "max_wall_seconds": 3600.0, "max_tool_calls": 500},
        "sandbox": {"backend": "local", "workdir": str(CONFIG_DIR.parent / "maverick-workspace"),
                    "timeout": 60},
        "keys": {},
    }

    # Step 1: welcome (no answer expected on first call)
    _recv()
    _send(_step(
        "deployment",
        "Where will Maverick run?",
        [
            "desktop (this computer)",
            "docker (local container)",
            "vps (remote server)",
            "phone (companion via channels)",
        ],
    ))

    ans = _recv()
    state["deployment"] = ans.split()[0]
    if state["deployment"] == "docker":
        state["sandbox"]["backend"] = "docker"

    # Step 2: providers
    _send(_step(
        "providers",
        "Which AI providers? (Anthropic is recommended for beginners)",
        [info["label"] for info in catalog.PROVIDERS.values()],
    ))
    ans = _recv()
    # For the GUI we pick the matching provider id by label.
    state["providers"] = [
        prov_id for prov_id, info in catalog.PROVIDERS.items() if info["label"] == ans
    ] or ["anthropic"]

    # Step 3: API keys (one question per provider, free text)
    for prov in state["providers"]:
        info = catalog.PROVIDERS[prov]
        env_name = info.get("env")
        if env_name:
            _send(_step(f"key_{env_name}", f"Paste your {env_name}", []))
            key = _recv()
            if key:
                state["keys"][env_name] = key

    # Step 4: channels
    _send(_step(
        "channels",
        "Enable any messaging channels? (Comma-separated; blank for none)",
        [f"{ch_id} ({label})" for ch_id, label, _ in CHANNELS],
    ))
    ans = _recv()
    # parse "telegram, discord" etc.
    if ans:
        picked_ids = [a.strip().split()[0] for a in ans.split(",") if a.strip()]
        for ch_id in picked_ids:
            info = next((c for c in CHANNELS if c[0] == ch_id), None)
            if info:
                state["channels"][ch_id] = {"enabled": True}
                state["channel_envs"].update(info[2])

    # Step 5: safety
    _send(_step(
        "safety",
        "Safety profile (recommended: balanced)",
        ["strict", "balanced", "permissive", "off"],
    ))
    ans = _recv() or "balanced"
    state["safety"]["profile"] = ans

    # Final: write config
    write_config(
        state["deployment"],
        state["providers"],
        state["role_models"],
        state["channels"],
        state["safety"],
        state["budget"],
        state["sandbox"],
        state["keys"],
    )
    _send(_step("__done__", "All set. Maverick is configured.", []))


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        _send({"id": "__error__", "question": str(e), "choices": []})
        sys.exit(1)
