"""The GitLab CI wrapper template must be valid YAML and actually run Maverick.

Mirrors the GitHub reusable workflow (deploy/github-action) for GitLab
users: a job that pip-installs maverick-agent and runs a goal on a pipeline.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE = _REPO_ROOT / "deploy" / "gitlab-ci" / "maverick.gitlab-ci.yml"


def test_gitlab_template_exists():
    assert _TEMPLATE.is_file(), f"missing GitLab CI template at {_TEMPLATE}"


def test_gitlab_template_parses_and_defines_maverick_job():
    data = yaml.safe_load(_TEMPLATE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "maverick" in data, "expected a top-level 'maverick' job"
    job = data["maverick"]
    steps = "\n".join(job.get("before_script", []) + job.get("script", []))
    # Installs the package and runs a goal.
    assert "pip install" in steps and "maverick-agent" in steps
    assert "maverick start" in steps


def test_gitlab_template_is_non_interactive_with_budget_cap():
    data = yaml.safe_load(_TEMPLATE.read_text(encoding="utf-8"))
    job = data["maverick"]
    # CI must not block on a consent prompt...
    assert job.get("variables", {}).get("MAVERICK_CONSENT_MODE") == "auto-deny"
    # ...and a hard cost cap must be configurable.
    assert "MAVERICK_MAX_DOLLARS" in data.get("variables", {})
