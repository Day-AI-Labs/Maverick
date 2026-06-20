"""Share a Maverick run as a sanitized, private GitHub gist.

``maverick share <goal-id>`` exports the run's trajectory via
``replay_export`` (which scrubs secrets) and uploads it as a PRIVATE gist,
returning the URL. Nothing is uploaded without an explicit GitHub token.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_GIST_API = "https://api.github.com/gists"


def build_gist_payload(goal_id: int) -> dict:
    """Assemble the gist API payload from a sanitized run export."""
    from .replay import export as replay_export
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / f"maverick-run-{goal_id}.json"
        replay_export.export_json(goal_id, out)
        content = out.read_text(encoding="utf-8")
    fname = f"maverick-run-{goal_id}.json"
    return {
        "description": f"Maverick run #{goal_id} (sanitized trajectory)",
        "public": False,  # secret gist -- shareable by URL, not listed/searchable
        "files": {fname: {"content": content}},
    }


def share_run(goal_id: int, token: str | None = None) -> str:
    """Upload the sanitized run as a private gist; return its URL.

    Token resolution: explicit arg > ``GITHUB_TOKEN`` > ``GH_TOKEN``. Raises
    if none is set (we never upload anonymously).
    """
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError(
            "no GitHub token: set GITHUB_TOKEN to share a run as a gist."
        )
    import httpx
    resp = httpx.post(
        _GIST_API,
        json=build_gist_payload(goal_id),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json().get("html_url", "")
