"""Build a pre-filled GitHub "new issue" URL from a failed run.

Lets a user "claim as bug report": gather a goal's failed-turn context,
scrub secrets, and produce a ``github.com/<repo>/issues/new?title=&body=``
link they can open to file a report with the context already filled in.
No network calls -- it just builds a URL the user opens in a browser.
"""
from __future__ import annotations

from urllib.parse import quote

DEFAULT_REPO = "cdayAI/Maverick"
# Keep the prefilled body well under GitHub's URL length limit so the link
# always opens; long error dumps are truncated.
_MAX_BODY_CHARS = 6000


def build_issue_url(
    repo: str, title: str, body: str, *, max_body: int = _MAX_BODY_CHARS,
) -> str:
    """Return a ``github.com/<repo>/issues/new`` prefill URL (title + body)."""
    if len(body) > max_body:
        body = body[:max_body] + "\n\n[... truncated]"
    return (
        f"https://github.com/{repo}/issues/new"
        f"?title={quote(title, safe='')}"
        f"&body={quote(body, safe='')}"
    )


def build_report(
    goal, error_events, *, repo: str = DEFAULT_REPO, version: str | None = None,
) -> str:
    """Build a prefilled bug-report URL from a goal's failed turns.

    ``goal`` exposes ``.id`` / ``.title`` / ``.status``; ``error_events`` is a
    list of objects with ``.agent`` / ``.content``. All free text is scrubbed
    of secrets (API keys, tokens) before it ever reaches the URL.
    """
    from .secrets import scrub

    gtitle = scrub(str(getattr(goal, "title", "") or "")).strip()
    title = f"Agent run failed: {gtitle or 'goal'}"[:120]
    lines = [
        "_Reported from a failed Maverick run (`maverick report-issue`)._",
        "",
        f"- Goal #{getattr(goal, 'id', '?')}: {gtitle}",
        f"- Status: {getattr(goal, 'status', '?')}",
    ]
    if version:
        lines.append(f"- Version: {version}")
    lines += ["", "### Errors", ""]
    if error_events:
        for e in error_events:
            agent = scrub(str(getattr(e, "agent", "?") or "?"))
            content = scrub(str(getattr(e, "content", "") or ""))
            lines.append(
                f"<details><summary>{agent}</summary>\n\n```\n{content}\n```\n</details>"
            )
    else:
        lines.append("_(no error events recorded)_")
    lines += ["", "### What I expected", "", "<!-- describe the expected behaviour -->"]
    return build_issue_url(repo, title, "\n".join(lines))
