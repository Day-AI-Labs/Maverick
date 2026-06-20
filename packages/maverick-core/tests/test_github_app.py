"""GitHub App webhook + payload parsing tests."""
from __future__ import annotations

import hashlib
import hmac

from maverick.github_app import (
    SLASH_TRIGGER,
    _trigger_labels,
    build_brief,
    parse_webhook,
    slugify,
    verify_signature,
)


class TestSignature:
    def test_valid_signature_accepts(self):
        secret = "s3cr3t"
        body = b'{"hello":"world"}'
        sig = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256,
        ).hexdigest()
        assert verify_signature(body, sig, secret) is True

    def test_wrong_signature_rejects(self):
        assert verify_signature(b"{}", "sha256=deadbeef", "s3cr3t") is False

    def test_missing_signature_rejects(self):
        assert verify_signature(b"{}", None, "s3cr3t") is False

    def test_no_secret_rejects(self):
        """No secret configured -> fail CLOSED (an unsigned request must not
        be enough to clone + drive a swarm). Matches issue_webhooks/webhooks."""
        assert verify_signature(b"{}", None, None) is False
        assert verify_signature(b"{}", "sha256=anything", None) is False


class TestParseWebhook:
    def _issues_labeled(self, label_name="maverick"):
        return {
            "action": "labeled",
            "repository": {"full_name": "octocat/spoon"},
            "issue": {"number": 42, "title": "Fix the bug",
                      "body": "Reproduction: ..."},
            "label": {"name": label_name},
            "sender": {"login": "alice"},
        }

    def test_issues_labeled_with_trigger(self):
        out = parse_webhook("issues", self._issues_labeled("maverick"))
        assert out is not None
        assert out.issue_number == 42
        assert out.trigger_label == "maverick"
        assert out.sender_login == "alice"

    def test_issues_labeled_with_non_trigger_label_returns_none(self):
        out = parse_webhook("issues", self._issues_labeled("question"))
        assert out is None

    def test_custom_trigger_labels(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_GH_TRIGGER_LABELS", "foo,bar")
        assert "foo" in _trigger_labels()
        assert "maverick" not in _trigger_labels()  # overridden
        out = parse_webhook("issues", self._issues_labeled("foo"))
        assert out is not None

    def test_issue_comment_with_slash_trigger(self):
        payload = {
            "action": "created",
            "repository": {"full_name": "octocat/spoon"},
            "issue": {"number": 7, "title": "x", "body": "y"},
            "comment": {
                "body": f"hey {SLASH_TRIGGER} look at this",
                "author_association": "OWNER",
            },
            "sender": {"login": "alice"},
        }
        out = parse_webhook("issue_comment", payload)
        assert out is not None
        assert out.comment_body and SLASH_TRIGGER in out.comment_body.lower()

    def test_issue_comment_from_unauthorized_author_returns_none(self):
        # The public (author_association NONE / CONTRIBUTOR / missing) must
        # NOT trigger a run via /maverick even with the slash command --
        # otherwise anyone can spend the operator's budget.
        for assoc in ("NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", ""):
            payload = {
                "action": "created",
                "repository": {"full_name": "octocat/spoon"},
                "issue": {"number": 7, "title": "x", "body": "y"},
                "comment": {
                    "body": f"{SLASH_TRIGGER} please fix",
                    "author_association": assoc,
                },
                "sender": {"login": "rando"},
            }
            assert parse_webhook("issue_comment", payload) is None, assoc

    def test_issue_comment_from_privileged_author_triggers(self):
        for assoc in ("OWNER", "MEMBER", "COLLABORATOR"):
            payload = {
                "action": "created",
                "repository": {"full_name": "octocat/spoon"},
                "issue": {"number": 7, "title": "x", "body": "y"},
                "comment": {
                    "body": f"{SLASH_TRIGGER} please fix",
                    "author_association": assoc,
                },
                "sender": {"login": "maint"},
            }
            out = parse_webhook("issue_comment", payload)
            assert out is not None and out.issue_number == 7, assoc

    def test_issue_comment_without_slash_returns_none(self):
        payload = {
            "action": "created",
            "repository": {"full_name": "octocat/spoon"},
            "issue": {"number": 7, "title": "x", "body": "y"},
            "comment": {"body": "just a regular comment"},
        }
        assert parse_webhook("issue_comment", payload) is None

    def test_unknown_event_returns_none(self):
        assert parse_webhook("push", {"action": "created"}) is None

    def test_issues_opened_returns_none(self):
        """Only labeled triggers; plain opened doesn't (would spam)."""
        payload = {
            "action": "opened",
            "repository": {"full_name": "octocat/spoon"},
            "issue": {"number": 1, "title": "x", "body": "y"},
        }
        assert parse_webhook("issues", payload) is None


class TestBuildBrief:
    def test_brief_includes_repo_issue_title_body(self):
        from maverick.github_app import WebhookPayload
        p = WebhookPayload(
            event="issues", action="labeled",
            repo_full_name="octocat/spoon",
            issue_number=42, issue_title="Fix the bug",
            issue_body="The thing breaks when...",
            trigger_label="maverick", sender_login="alice",
        )
        brief = build_brief(p)
        assert "octocat/spoon" in brief
        assert "#42" in brief
        assert "Fix the bug" in brief
        assert "The thing breaks when..." in brief


class TestSlugify:
    def test_basic(self):
        assert slugify("Fix the bug in foo") == "fix-the-bug-in-foo"

    def test_special_chars(self):
        assert slugify("Hello! World #2") == "hello-world-2"

    def test_truncates_long(self):
        long = "a" * 100
        assert len(slugify(long, max_len=40)) <= 40

    def test_empty_falls_back(self):
        assert slugify("") == "issue"
        assert slugify("!!!") == "issue"


class TestProcessIssueGitTimeout:
    """A hung local git call must surface as a clean PRResult, not a hang/crash."""

    def _payload(self):
        from maverick.github_app import WebhookPayload
        return WebhookPayload(
            event="issues", action="labeled", repo_full_name="octocat/spoon",
            issue_number=7, issue_title="t", issue_body="b",
            trigger_label="maverick", sender_login="alice",
        )

    def test_checkout_timeout_returns_error(self, monkeypatch, tmp_path):
        import asyncio
        import subprocess

        from maverick import github_app as ga

        monkeypatch.setattr(ga, "clone_repo", lambda *a, **k: tmp_path)

        def _boom(*a, **k):
            raise subprocess.TimeoutExpired(cmd="git", timeout=ga._GIT_TIMEOUT)

        monkeypatch.setattr(ga.subprocess, "run", _boom)

        res = asyncio.run(ga.process_issue(self._payload(), token="x"))
        assert res.pr_url is None
        assert "checkout failed" in (res.error or "")

    def test_checkout_calls_are_time_boxed(self, monkeypatch, tmp_path):
        # Every git call in the post-clone path passes a timeout (regression:
        # they previously had none and could hang the webhook handler).
        import asyncio
        import subprocess

        from maverick import github_app as ga

        monkeypatch.setattr(ga, "clone_repo", lambda *a, **k: tmp_path)
        seen_timeouts = []
        real = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

        def _spy(*a, **k):
            seen_timeouts.append(k.get("timeout"))
            return real

        monkeypatch.setattr(ga.subprocess, "run", _spy)
        # Stop after the checkout by making the branch-create the only call we
        # need to observe: force an early "no changes" return path.
        monkeypatch.setattr(ga, "build_sandbox", lambda **k: object(), raising=False)

        async def _fake_run_goal(*a, **k):
            return "did nothing"

        monkeypatch.setattr(ga, "run_goal", _fake_run_goal, raising=False)
        monkeypatch.setattr("maverick.world_model.WorldModel.create_goal",
                            lambda self, *a, **k: 1, raising=False)
        monkeypatch.setattr("maverick.llm.LLM.__init__", lambda self, *a, **k: None)

        asyncio.run(ga.process_issue(self._payload(), token="x"))
        # At least the checkout ran, and every observed call carried a timeout.
        assert seen_timeouts
        assert all(t is not None for t in seen_timeouts)
