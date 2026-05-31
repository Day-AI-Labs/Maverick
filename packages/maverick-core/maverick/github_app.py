"""GitHub App mode — assign an issue, get a PR back.

OpenHands and Copilot Agent ship this pattern in 2026: maintainer labels
or @-mentions a GitHub issue, the agent clones the repo, attempts a fix,
pushes a branch, opens a PR. Maverick now supports the same flow.

This module is the WEBHOOK RECEIVER + PR FACTORY. The actual coding
work runs in a Maverick swarm with the GitHub issue body as the brief.

Modes:
  - `maverick gh-app webhook`  : run a FastAPI listener on a public port,
    accept GitHub `issues.labeled` + `issue_comment.created` events.
  - `maverick gh-app process <issue-url>` : one-shot run against a
    specific issue URL (useful for CLI / cron / debugging without a
    webhook).

Trigger conditions (any of):
  1. issue labeled with one of MAVERICK_TRIGGER_LABELS (default
     "maverick", "automate")
  2. issue comment containing "/maverick" by a user with write access

Output:
  - new branch `maverick/issue-<n>-<slug>`
  - PR linked to the issue with the agent's FINAL as body
  - `--draft` by default per CLAUDE.md repo policy
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import logging
import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


# Default labels that trigger a Maverick run.
DEFAULT_LABELS = ("maverick", "automate", "ai-fix")

# Slash-command that triggers a run from an issue comment.
SLASH_TRIGGER = "/maverick"

# A comment author must have write-ish access to trigger a run via the
# slash command. GitHub's author_association reflects the commenter's
# relationship to the repo; anything below COLLABORATOR (CONTRIBUTOR,
# FIRST_TIME_CONTRIBUTOR, NONE, ...) is the general public and must not be
# able to spend the operator's API budget by commenting "/maverick".
_PRIVILEGED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


@dataclass
class WebhookPayload:
    """Normalized event from GitHub's webhook surface."""
    event: str                # "issues" | "issue_comment"
    action: str               # "labeled" | "created" | ...
    repo_full_name: str       # "owner/name"
    issue_number: int
    issue_title: str
    issue_body: str
    trigger_label: str | None = None
    comment_body: str | None = None
    sender_login: str = ""


def verify_signature(
    body: bytes,
    signature_header: str | None,
    secret: str | None,
) -> bool:
    """HMAC-SHA256 verification of GitHub's X-Hub-Signature-256 header.

    Defends against webhook spoofing. Fails CLOSED: a missing/empty secret
    rejects the request, matching ``issue_webhooks`` and ``webhooks`` (which
    also fail closed). The receiver this guards clones repos and drives a
    swarm that runs shell, so an unsigned request must never be enough to
    trigger a run -- the previous fail-open branch accepted *every* request
    when the operator forgot to set MAVERICK_GH_APP_WEBHOOK_SECRET.
    """
    if not secret:
        log.warning(
            "GH webhook signature check FAILED CLOSED: no secret configured "
            "(set MAVERICK_GH_APP_WEBHOOK_SECRET). Rejecting the request."
        )
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def parse_webhook(event: str, payload: dict) -> WebhookPayload | None:
    """Normalize the GitHub webhook payload.

    Returns None for events we don't care about (e.g., issues.opened
    without a trigger label).
    """
    action = payload.get("action", "")
    repo = payload.get("repository", {}).get("full_name", "")
    issue = payload.get("issue", {}) or {}
    sender = (payload.get("sender") or {}).get("login", "")

    if event == "issues" and action == "labeled":
        label_name = (payload.get("label") or {}).get("name", "")
        if label_name.lower() not in _trigger_labels():
            return None
        return WebhookPayload(
            event=event, action=action,
            repo_full_name=repo,
            issue_number=issue.get("number", 0),
            issue_title=issue.get("title", ""),
            issue_body=issue.get("body", "") or "",
            trigger_label=label_name,
            sender_login=sender,
        )

    if event == "issue_comment" and action == "created":
        comment_obj = payload.get("comment") or {}
        comment = comment_obj.get("body", "") or ""
        if SLASH_TRIGGER not in comment.lower():
            return None
        # Authorization: only repo-privileged commenters may trigger a run.
        # Without this, any public user can comment "/maverick" and spend
        # the operator's budget on a clone + swarm run.
        association = (comment_obj.get("author_association") or "").upper()
        if association not in _PRIVILEGED_ASSOCIATIONS:
            log.warning(
                "ignoring /maverick from unauthorized commenter %s "
                "(author_association=%s)", sender, association or "NONE",
            )
            return None
        return WebhookPayload(
            event=event, action=action,
            repo_full_name=repo,
            issue_number=issue.get("number", 0),
            issue_title=issue.get("title", ""),
            issue_body=issue.get("body", "") or "",
            comment_body=comment,
            sender_login=sender,
        )

    return None


def _trigger_labels() -> set[str]:
    raw = os.environ.get("MAVERICK_GH_TRIGGER_LABELS", "")
    if raw:
        return {x.strip().lower() for x in raw.split(",") if x.strip()}
    return set(DEFAULT_LABELS)


def build_brief(payload: WebhookPayload) -> str:
    """Render the issue into a Maverick goal brief."""
    return (
        f"GitHub issue: {payload.repo_full_name}#{payload.issue_number}\n"
        f"Title: {payload.issue_title}\n\n"
        f"Issue body:\n{payload.issue_body}\n\n"
        "Implement a minimal fix or feature satisfying the issue. "
        "Stage and commit your work; the harness will push and open a PR."
    )


def slugify(title: str, max_len: int = 40) -> str:
    """Issue title -> kebab-case branch slug."""
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:max_len] or "issue"


@dataclass
class PRResult:
    branch_name: str
    pr_url: str | None
    workdir: Path
    summary: str   # agent's FINAL output
    error: str | None = None


@contextlib.contextmanager
def _git_token_env(token: str | None) -> Iterator[dict]:
    """Yield an env that feeds ``token`` to git via ``GIT_ASKPASS``.

    Embedding the token in the clone URL (``https://x-access-token:TOKEN@``)
    leaked it three ways: into ``ps``/argv, into the cloned repo's persisted
    ``origin`` URL on disk, and into ``CalledProcessError`` messages on a
    failed clone (which we surface in ``PRResult.error``). Routing it through
    an ephemeral askpass helper keeps the token out of all three -- the URL
    carries only the ``x-access-token`` username, git asks the helper for the
    password, and the helper file is removed on exit.
    """
    if not token:
        yield dict(os.environ)
        return
    fd, path = tempfile.mkstemp(prefix="mvk-gh-askpass-", suffix=".sh")
    try:
        with os.fdopen(fd, "w") as f:
            f.write('#!/bin/sh\nexec printf "%s" "$MAVERICK_GH_TOKEN"\n')
        os.chmod(path, 0o700)
        yield {
            **os.environ,
            "GIT_ASKPASS": path,
            "GIT_TERMINAL_PROMPT": "0",
            "MAVERICK_GH_TOKEN": token,
        }
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


def clone_repo(repo_full_name: str, token: str, dest: Path) -> Path:
    """Shallow-clone `owner/repo` to `dest`. Requires `git` on PATH.

    The token is supplied via ``GIT_ASKPASS`` (see ``_git_token_env``) so it
    never lands in argv, the persisted remote URL, or error output.
    """
    url = f"https://x-access-token@github.com/{repo_full_name}.git"
    with _git_token_env(token) as env:
        subprocess.run(
            ["git", "clone", "--depth", "10", url, str(dest)],
            check=True, capture_output=True, timeout=120, env=env,
        )
    return dest


def create_pr_via_gh(
    workdir: Path,
    branch_name: str,
    issue_number: int,
    pr_title: str,
    pr_body: str,
    *,
    draft: bool = True,
) -> str | None:
    """Use the `gh` CLI to push + open a draft PR. Returns the PR URL or None.

    The PR is opened as a draft per repo policy (see CLAUDE.md). The
    caller is expected to have a `gh auth login` set up in the
    environment (or GH_TOKEN set), since we can't reasonably ship a
    token-mint flow inside Maverick.
    """
    try:
        # The cloned origin no longer embeds the token (see clone_repo), so
        # feed it to the push via the same askpass helper.
        push_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        with _git_token_env(push_token) as env:
            subprocess.run(
                ["git", "-C", str(workdir), "push", "-u", "origin", branch_name],
                check=True, capture_output=True, timeout=60, env=env,
            )
        args = [
            "gh", "pr", "create",
            "--head", branch_name,
            "--title", pr_title,
            "--body", pr_body,
            "--repo", _origin_full_name(workdir),
        ]
        if draft:
            args.append("--draft")
        out = subprocess.run(
            args, check=True, capture_output=True, timeout=60, text=True,
        )
        url = (out.stdout or "").strip().splitlines()[-1] if out.stdout else ""
        return url or None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.warning("PR creation via gh failed: %s", e)
        return None


def _origin_full_name(workdir: Path) -> str:
    """Get `owner/repo` from the origin URL."""
    try:
        out = subprocess.run(
            ["git", "-C", str(workdir), "remote", "get-url", "origin"],
            check=True, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return ""
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?/?$", out)
    return m.group(1) if m else ""


async def process_issue(
    payload: WebhookPayload,
    *,
    token: str | None = None,
    max_dollars: float = 5.0,
    max_wall_seconds: float = 1800.0,
    draft: bool = True,
) -> PRResult:
    """End-to-end: clone, run swarm, push branch, open PR.

    Requires:
      - GH_TOKEN env (or `token` arg): GitHub PAT with repo write
      - ANTHROPIC_API_KEY in env
      - git + gh on PATH
    """
    token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        return PRResult(
            branch_name="", pr_url=None, workdir=Path(),
            summary="", error="GH_TOKEN not set",
        )

    branch_name = f"maverick/issue-{payload.issue_number}-{slugify(payload.issue_title)}"
    workdir = Path(tempfile.mkdtemp(prefix="maverick-gh-"))
    try:
        clone_repo(payload.repo_full_name, token, workdir)
    except subprocess.CalledProcessError as e:
        # Defense in depth: scrub in case any git output still echoes a
        # credential-shaped string into the error we hand back.
        from .secrets import scrub
        return PRResult(
            branch_name=branch_name, pr_url=None, workdir=workdir,
            summary="", error=scrub(f"clone failed: {e}"),
        )

    # Create the branch in the clone before the agent starts so its
    # commits land where we expect.
    subprocess.run(
        ["git", "-C", str(workdir), "checkout", "-b", branch_name],
        check=True, capture_output=True,
    )

    from .budget import Budget
    from .llm import LLM
    from .orchestrator import run_goal
    from .sandbox import build_sandbox
    from .world_model import WorldModel

    world = WorldModel()
    llm = LLM()
    sandbox = build_sandbox(workdir=str(workdir))
    gid = world.create_goal(
        f"gh:{payload.repo_full_name}#{payload.issue_number}",
        build_brief(payload),
    )
    summary = await run_goal(
        llm, world, Budget(
            max_dollars=max_dollars, max_wall_seconds=max_wall_seconds,
        ),
        gid, sandbox=sandbox, max_depth=3,
    )

    # If the agent committed anything, push + open PR.
    diff_out = subprocess.run(
        ["git", "-C", str(workdir), "diff", "--cached", "--quiet"],
        capture_output=True,
    )
    # Returncode 1 = changes staged; 0 = nothing staged.
    has_staged = diff_out.returncode == 1
    if not has_staged:
        # Auto-add everything modified so a sloppy agent run still
        # produces a PR (operator can review the diff).
        subprocess.run(
            ["git", "-C", str(workdir), "add", "-A"],
            check=False, capture_output=True,
        )
        # Empty changeset -> no PR.
        check = subprocess.run(
            ["git", "-C", str(workdir), "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if check.returncode == 0:
            return PRResult(
                branch_name=branch_name, pr_url=None, workdir=workdir,
                summary=summary,
                error="agent finished but produced no changes",
            )

    subprocess.run(
        ["git", "-C", str(workdir), "commit", "-m",
         f"Maverick: address #{payload.issue_number}"],
        check=False, capture_output=True,
    )

    pr_title = f"Maverick: {payload.issue_title[:60]}"
    pr_body = (
        f"Closes #{payload.issue_number}\n\n"
        f"## Maverick summary\n\n{summary}\n\n"
        f"_Triggered by {payload.sender_login} via "
        f"{'label ' + payload.trigger_label if payload.trigger_label else SLASH_TRIGGER}._"
    )
    pr_url = create_pr_via_gh(
        workdir, branch_name,
        payload.issue_number, pr_title, pr_body, draft=draft,
    )
    return PRResult(
        branch_name=branch_name, pr_url=pr_url,
        workdir=workdir, summary=summary,
    )
