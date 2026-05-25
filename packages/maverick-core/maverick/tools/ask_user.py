"""Async question-to-user tool.

The agent queues a question into the world model and gets a sentinel back.
The orchestrator decides whether to keep going (with other independent
sub-tasks) or pause. The user answers later via `maverick answer`.
"""
from __future__ import annotations

from . import Tool


def ask_user(world) -> Tool:
    def fn(args: dict) -> str:
        qid = world.ask(args["question"])
        return f"QUEUED question #{qid}. The user will answer asynchronously. Continue with independent work if possible; otherwise pause."

    return Tool(
        name="ask_user",
        description=(
            "Queue a question for the user. They will answer asynchronously. "
            "Use sparingly and batch related questions into one. Prefer doing "
            "independent work first; only ask when truly blocked."
        ),
        input_schema={
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
        fn=fn,
    )
