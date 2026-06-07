"""knowledge_search: let a domain agent query its own uploaded documents.

Bound to the agent's ``knowledge_sources`` (the DomainProfile's collections), so
a finance agent searches only finance documents -- knowledge respects the same
compartment bulkheads. The KnowledgeBase lives on the shared SwarmContext; this
tool is a thin, per-agent binding over it. Optional: registered only when a
knowledge base is configured for the run.
"""
from __future__ import annotations

from . import Tool


def knowledge_search_tool(kb, collections: list[str]) -> Tool:
    async def fn(args: dict) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return "ERROR: 'query' is required."
        try:
            k = int(args.get("k", 5))
        except (TypeError, ValueError):
            k = 5
        try:
            return kb.search_formatted(collections, query, k)
        except Exception as e:  # never break the agent loop on a KB error
            return f"knowledge_search unavailable: {type(e).__name__}"

    return Tool(
        name="knowledge_search",
        description=(
            "Search this domain's uploaded documents for passages relevant to a "
            "query. Returns the top matches with their source. Ground answers in "
            "the business's own documents before answering from general knowledge."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for."},
                "k": {"type": "integer", "description": "Max passages (default 5)."},
            },
            "required": ["query"],
        },
        fn=fn,
    )
