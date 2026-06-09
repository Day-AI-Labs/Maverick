"""Container build tool (roadmap: 2028 H1 capabilities — "container build tool").

Builds a container image from a Dockerfile + context directory by issuing
``docker build`` through the sandbox chokepoint (CLAUDE.md rule #4 — never a
bare ``subprocess``). The agent supplies the context dir, image tag, and
optional build-args; the tag and build-arg keys are validated so nothing
model-supplied can break out of the argv. Returns the build status + a tail of
the output.

ops:
  - build(context, tag[, dockerfile][, build_args][, timeout])
"""
from __future__ import annotations

import os
import re
from typing import Any

from . import Tool, sandbox_run

# Docker tag grammar (simplified): name[:tag], lowercase name, optional registry/path.
_TAG = re.compile(r"^[a-z0-9]([a-z0-9._/-]*[a-z0-9])?(:[A-Za-z0-9._-]+)?$")
_ARG_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _build(sandbox: Any, args: dict[str, Any]) -> str:
    context = (args.get("context") or ".").strip()
    if not os.path.isdir(context):
        return f"ERROR: context dir not found: {context}"
    tag = (args.get("tag") or "").strip()
    if not tag or not _TAG.match(tag):
        return "ERROR: missing or invalid 'tag' (expected name[:tag])"
    dockerfile = (args.get("dockerfile") or "Dockerfile").strip()
    df_path = dockerfile if os.path.isabs(dockerfile) else os.path.join(context, dockerfile)
    if not os.path.isfile(df_path):
        return f"ERROR: Dockerfile not found: {df_path}"

    argv = ["docker", "build", "-t", tag, "-f", df_path]
    bargs = args.get("build_args") or {}
    if isinstance(bargs, dict):
        for k, v in bargs.items():
            if not _ARG_KEY.match(str(k)):
                return f"ERROR: invalid build-arg key {k!r}"
            argv += ["--build-arg", f"{k}={v}"]
    argv.append(context)

    try:
        timeout = float(args.get("timeout", 600))
    except (TypeError, ValueError):
        timeout = 600.0
    code, out, err = sandbox_run(sandbox, argv, timeout=timeout)
    tail = (out or "")[-1500:]
    if err:
        tail = (tail + "\n" + err[-500:]).strip()
    status = "ok" if code == 0 else f"FAILED (exit {code})"
    return f"docker build {status} for {tag}\n{tail}".strip()


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["build"]},
        "context": {"type": "string", "description": "build context directory"},
        "tag": {"type": "string", "description": "image tag, e.g. myapp:dev"},
        "dockerfile": {"type": "string", "description": "Dockerfile path (default: <context>/Dockerfile)"},
        "build_args": {"type": "object", "description": "--build-arg KEY=VALUE pairs"},
        "timeout": {"type": "number", "description": "build timeout seconds (default 600)"},
    },
    "required": ["context", "tag"],
}


def container_build(sandbox: Any) -> Tool:
    return Tool(
        name="container_build",
        description=(
            "Build a container image from a Dockerfile + context via 'docker "
            "build', routed through the sandbox. op=build with 'context' (dir) "
            "and 'tag' (name[:tag]); optional 'dockerfile', 'build_args' (object), "
            "'timeout'. Tag and build-arg keys are validated. Returns status + "
            "an output tail."
        ),
        input_schema=_SCHEMA,
        fn=lambda args: _build(sandbox, args),
    )
