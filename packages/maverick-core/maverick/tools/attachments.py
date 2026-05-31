"""list_attachments tool.

Lets the agent enumerate files the user uploaded with the goal so it
can decide which ones to read. Each row returns filename / mime / size /
absolute path; the agent then uses the existing ``read_file`` tool to
pick up text content. Images are embedded as vision blocks separately
(see ``maverick.attachments.content_blocks_for_goal``).
"""
from __future__ import annotations

from . import Tool


def list_attachments_tool(world, goal_id: int | None) -> Tool:
    def fn(_args: dict) -> str:
        if goal_id is None:
            return "(no goal context; no attachments)"
        atts = world.list_attachments(goal_id)
        if not atts:
            return "(no attachments)"
        lines = [
            f"{a.id}  {a.filename}  {a.mime}  {a.size_bytes}B  {a.path}"
            for a in atts
        ]
        return "\n".join(lines)

    return Tool(
        name="list_attachments",
        description=(
            "List files the user uploaded with this goal. Returns one line per "
            "attachment: id, filename, mime, size, path. Use `read_file` with "
            "the path to read text content; images are already visible to you."
        ),
        input_schema={
            "type": "object",
            "properties": {},
        },
        fn=fn,
    )
