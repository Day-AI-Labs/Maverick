"""Q1 2026 batch 6: MkDocs config, docs landing, docs CI, reusable agent-on-PR workflow."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_mkdocs_yml_exists_and_parses():
    """Top-level mkdocs.yml configures the MkDocs Material site."""
    p = REPO_ROOT / "mkdocs.yml"
    assert p.is_file()
    body = p.read_text()
    # Sanity: required fields appear.
    for k in ("site_name:", "theme:", "nav:", "name: material"):
        assert k in body, f"mkdocs.yml missing {k!r}"


def test_mkdocs_yml_navigation_references_existing_files():
    """nav: entries must point to files that actually exist."""
    p = REPO_ROOT / "mkdocs.yml"
    body = p.read_text()
    # Naive: extract any docs/ relative path the nav: block points to.
    # MkDocs paths are relative to docs/.
    import re

    nav_targets = re.findall(r":\s+([a-zA-Z0-9_/.-]+\.md)\s*$", body, flags=re.MULTILINE)
    assert nav_targets, "no nav targets parsed from mkdocs.yml"
    missing: list[str] = []
    for rel in nav_targets:
        target = REPO_ROOT / "docs" / rel
        # Allow paths that point to top-level files (CONTRIBUTING.md etc) -
        # the docs.yml workflow symlinks them into docs/ on build.
        top_level = REPO_ROOT / rel
        if not target.is_file() and not top_level.is_file():
            missing.append(rel)
    assert not missing, f"nav references missing files: {missing}"


def test_docs_index_landing_exists():
    p = REPO_ROOT / "docs" / "index.md"
    assert p.is_file()
    body = p.read_text()
    # Landing must mention the project's pitch fields.
    for keyword in ("Maverick", "Quick start", "Pricing", "Roadmap"):
        assert keyword in body, f"index.md missing section: {keyword}"


def test_docs_workflow_exists():
    p = REPO_ROOT / ".github" / "workflows" / "docs.yml"
    assert p.is_file()
    body = p.read_text()
    # Must build with mkdocs and deploy to Pages.
    assert "mkdocs" in body
    assert "deploy-pages" in body or "github-pages" in body.lower()


def test_reusable_agent_on_pr_workflow_exists():
    p = REPO_ROOT / ".github" / "workflows" / "agent-on-pr.yml"
    assert p.is_file()
    body = p.read_text()
    # Must declare reusable workflow_call and required inputs.
    assert "workflow_call" in body
    assert "goal:" in body
    assert "max_dollars:" in body
    # Posts to PR via REST.
    assert "createComment" in body or "pull-requests: write" in body


def test_publish_workflow_still_present():
    """Earlier PyPI publish workflow shouldn't have been clobbered."""
    p = REPO_ROOT / ".github" / "workflows" / "publish.yml"
    assert p.is_file()
    body = p.read_text()
    assert "pypa/gh-action-pypi-publish" in body


def test_conventional_commits_workflow_still_present():
    p = REPO_ROOT / ".github" / "workflows" / "conventional-commits.yml"
    assert p.is_file()
