"""Filesystem tools backed by the sandbox."""
from __future__ import annotations

from pathlib import Path

from . import Tool


def read_file(sandbox) -> Tool:
    def fn(args: dict) -> str:
        path = args["path"]
        result = sandbox.exec(f"cat {path}")
        if not result.ok:
            return f"ERROR: {result.stderr}"
        return result.stdout

    return Tool(
        name="read_file",
        description="Read a file from the workspace.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Path to read."}},
            "required": ["path"],
        },
        fn=fn,
    )


def write_file(sandbox) -> Tool:
    def fn(args: dict) -> str:
        path = Path(sandbox.workdir) / args["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"])
        return f"wrote {len(args['content'])} bytes to {path}"

    return Tool(
        name="write_file",
        description="Write content to a file in the workspace. Overwrites if it exists.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        fn=fn,
    )


def list_dir(sandbox) -> Tool:
    def fn(args: dict) -> str:
        path = args.get("path", ".")
        result = sandbox.exec(f"ls -la {path}")
        return result.stdout if result.ok else f"ERROR: {result.stderr}"

    return Tool(
        name="list_dir",
        description="List files in a directory.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
        },
        fn=fn,
    )
