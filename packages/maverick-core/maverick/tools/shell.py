"""Shell tool. Sandbox-mediated."""
from __future__ import annotations

from . import Tool


def shell(sandbox) -> Tool:
    def fn(args: dict) -> str:
        result = sandbox.exec(args["cmd"])
        out = result.stdout
        if result.stderr:
            out += f"\n[stderr]\n{result.stderr}"
        out += f"\n[exit {result.exit_code}]"
        return out

    return Tool(
        name="shell",
        description="Run a shell command in the sandbox. Use for builds, tests, scripts, etc.",
        input_schema={
            "type": "object",
            "properties": {"cmd": {"type": "string"}},
            "required": ["cmd"],
        },
        fn=fn,
    )
