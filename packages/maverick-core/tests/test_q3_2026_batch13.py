"""Q3 2026 batch 13 — 15 SaaS / media tools + workflow engine.

Plausible / Mixpanel / Calendly / Zoom / Spotify / HomeAssistant /
Reddit / Bitbucket / SES / SNS / ffmpeg / pandoc / ImageMagick /
GA4 / Plaid + maverick.workflow.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


def _fake_httpx(monkeypatch, **methods):
    mod = types.ModuleType("httpx")
    for n, v in methods.items():
        setattr(mod, n, v)
    monkeypatch.setitem(sys.modules, "httpx", mod)
    return mod


def _resp(status, body):
    r = MagicMock()
    r.status_code = status
    if isinstance(body, (dict, list)):
        r.json = MagicMock(return_value=body)
        r.text = str(body)
    else:
        r.json = MagicMock(side_effect=ValueError("not json"))
        r.text = str(body)
    return r


# ---------- Plausible ----------

def test_plausible_requires_op():
    from maverick.tools.plausible_tool import plausible_tool
    assert "op is required" in plausible_tool().fn({})


def test_plausible_event_no_key(monkeypatch):
    monkeypatch.delenv("PLAUSIBLE_API_KEY", raising=False)
    _fake_httpx(monkeypatch, post=MagicMock(return_value=_resp(202, "")))
    from maverick.tools.plausible_tool import plausible_tool
    out = plausible_tool().fn({
        "op": "event", "site_id": "example.com", "name": "signup",
    })
    assert "accepted" in out


def test_plausible_aggregate_requires_key(monkeypatch):
    monkeypatch.delenv("PLAUSIBLE_API_KEY", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.plausible_tool import plausible_tool
    out = plausible_tool().fn({"op": "aggregate", "site_id": "x.com"})
    assert "PLAUSIBLE_API_KEY" in out


def test_plausible_aggregate_renders(monkeypatch):
    monkeypatch.setenv("PLAUSIBLE_API_KEY", "tok")
    body = {"results": {"visitors": {"value": 42},
                         "pageviews": {"value": 100}}}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.plausible_tool import plausible_tool
    out = plausible_tool().fn({"op": "aggregate", "site_id": "x.com"})
    assert "visitors: 42" in out and "pageviews: 100" in out


# ---------- Mixpanel ----------

def test_mixpanel_requires_op():
    from maverick.tools.mixpanel_tool import mixpanel_tool
    assert "op is required" in mixpanel_tool().fn({})


def test_mixpanel_track_missing_token(monkeypatch):
    monkeypatch.delenv("MIXPANEL_PROJECT_TOKEN", raising=False)
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.mixpanel_tool import mixpanel_tool
    out = mixpanel_tool().fn({"op": "track", "event": "x", "distinct_id": "u"})
    assert "MIXPANEL_PROJECT_TOKEN" in out


def test_mixpanel_track_posts(monkeypatch):
    monkeypatch.setenv("MIXPANEL_PROJECT_TOKEN", "tok")
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "1"
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.post = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.mixpanel_tool import mixpanel_tool
    out = mixpanel_tool().fn({
        "op": "track", "event": "signup", "distinct_id": "user-1",
        "properties": {"plan": "pro"},
    })
    assert "tracked 'signup'" in out


# ---------- Calendly ----------

def test_calendly_requires_op():
    from maverick.tools.calendly_tool import calendly_tool
    assert "op is required" in calendly_tool().fn({})


def test_calendly_me_missing_token(monkeypatch):
    monkeypatch.delenv("CALENDLY_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.calendly_tool import calendly_tool
    out = calendly_tool().fn({"op": "me"})
    assert "CALENDLY_TOKEN" in out


def test_calendly_cancel_dry_run(monkeypatch):
    monkeypatch.setenv("CALENDLY_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.calendly_tool import calendly_tool
    out = calendly_tool().fn({"op": "cancel", "event_uuid": "abc"})
    assert "DRY RUN" in out


def test_calendly_events_renders(monkeypatch):
    monkeypatch.setenv("CALENDLY_TOKEN", "tok")
    monkeypatch.setenv("CALENDLY_USER_URI", "https://api.calendly.com/users/U")
    body = {"collection": [
        {"uri": "https://api.calendly.com/scheduled_events/E1",
         "status": "active", "start_time": "2026-06-01T10:00:00Z",
         "name": "Intro chat"},
    ]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.calendly_tool import calendly_tool
    out = calendly_tool().fn({"op": "events"})
    assert "Intro chat" in out and "active" in out


# ---------- Zoom ----------

def test_zoom_requires_op():
    from maverick.tools.zoom_tool import zoom_tool
    assert "op is required" in zoom_tool().fn({})


def test_zoom_missing_token(monkeypatch):
    monkeypatch.delenv("ZOOM_OAUTH_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.zoom_tool import zoom_tool
    out = zoom_tool().fn({"op": "meetings"})
    assert "ZOOM_OAUTH_TOKEN" in out


def test_zoom_meeting_create_dry_run(monkeypatch):
    monkeypatch.setenv("ZOOM_OAUTH_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.zoom_tool import zoom_tool
    out = zoom_tool().fn({
        "op": "meeting_create", "topic": "demo",
        "start_time": "2026-06-01T10:00:00Z",
    })
    assert "DRY RUN" in out


def test_zoom_meetings_renders(monkeypatch):
    monkeypatch.setenv("ZOOM_OAUTH_TOKEN", "tok")
    body = {"meetings": [{
        "id": "123", "start_time": "2026-06-01T10:00:00Z",
        "topic": "Standup",
    }]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.zoom_tool import zoom_tool
    out = zoom_tool().fn({"op": "meetings"})
    assert "Standup" in out


# ---------- Spotify ----------

def test_spotify_requires_op():
    from maverick.tools.spotify_tool import spotify_tool
    assert "op is required" in spotify_tool().fn({})


def test_spotify_missing_token(monkeypatch):
    monkeypatch.delenv("SPOTIFY_ACCESS_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.spotify_tool import spotify_tool
    out = spotify_tool().fn({"op": "search", "q": "x"})
    assert "SPOTIFY_ACCESS_TOKEN" in out


def test_spotify_pause_dry_run(monkeypatch):
    monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "tok")
    _fake_httpx(monkeypatch, put=MagicMock())
    from maverick.tools.spotify_tool import spotify_tool
    out = spotify_tool().fn({"op": "pause"})
    assert "DRY RUN" in out


def test_spotify_search_renders(monkeypatch):
    monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "tok")
    body = {"tracks": {"items": [
        {"name": "Bohemian Rhapsody", "uri": "spotify:track:1",
         "artists": [{"name": "Queen"}]},
    ]}}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.spotify_tool import spotify_tool
    out = spotify_tool().fn({"op": "search", "q": "queen"})
    assert "Bohemian Rhapsody" in out and "Queen" in out


# ---------- Home Assistant ----------

def test_hass_requires_op():
    from maverick.tools.home_assistant_tool import home_assistant_tool
    assert "op is required" in home_assistant_tool().fn({})


def test_hass_missing_config(monkeypatch):
    monkeypatch.delenv("HASS_URL", raising=False)
    monkeypatch.delenv("HASS_TOKEN", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.home_assistant_tool import home_assistant_tool
    out = home_assistant_tool().fn({"op": "states"})
    assert "HASS_URL" in out


def test_hass_call_service_dry_run(monkeypatch):
    monkeypatch.setenv("HASS_URL", "http://hass.local:8123")
    monkeypatch.setenv("HASS_TOKEN", "tok")
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.home_assistant_tool import home_assistant_tool
    out = home_assistant_tool().fn({
        "op": "call_service", "domain": "light", "service": "turn_on",
        "data": {"entity_id": "light.living"},
    })
    assert "DRY RUN" in out


def test_hass_states_filters_by_domain(monkeypatch):
    monkeypatch.setenv("HASS_URL", "http://hass.local:8123")
    monkeypatch.setenv("HASS_TOKEN", "tok")
    body = [
        {"entity_id": "light.living", "state": "on",
         "attributes": {"friendly_name": "Living Room"}},
        {"entity_id": "switch.fan", "state": "off",
         "attributes": {"friendly_name": "Fan"}},
    ]
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.home_assistant_tool import home_assistant_tool
    out = home_assistant_tool().fn({"op": "states", "domain": "light"})
    assert "light.living" in out and "switch.fan" not in out


# ---------- Reddit ----------

def test_reddit_requires_op():
    from maverick.tools.reddit_tool import reddit_tool
    assert "op is required" in reddit_tool().fn({})


def test_reddit_subreddit_renders(monkeypatch):
    body = {"data": {"children": [
        {"data": {"subreddit": "python", "score": 200,
                  "num_comments": 30, "title": "PEP 800 dropped"}},
    ]}}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.reddit_tool import reddit_tool
    out = reddit_tool().fn({"op": "subreddit", "name": "python"})
    assert "PEP 800 dropped" in out and "python" in out


def test_reddit_post_renders(monkeypatch):
    body = [{"data": {"children": [{"data": {
        "title": "TIL", "subreddit": "showerthoughts",
        "score": 42, "author": "alice", "selftext": "Body",
        "permalink": "/r/x/c/abc/",
    }}]}}]
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.reddit_tool import reddit_tool
    out = reddit_tool().fn({"op": "post", "post_id": "abc"})
    assert "TIL" in out and "alice" in out


# ---------- Bitbucket ----------

def test_bitbucket_requires_op():
    from maverick.tools.bitbucket_tool import bitbucket_tool
    assert "op is required" in bitbucket_tool().fn({})


def test_bitbucket_missing_credentials(monkeypatch):
    monkeypatch.delenv("BITBUCKET_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("BITBUCKET_USERNAME", raising=False)
    monkeypatch.delenv("BITBUCKET_APP_PASSWORD", raising=False)
    _fake_httpx(monkeypatch, get=MagicMock())
    from maverick.tools.bitbucket_tool import bitbucket_tool
    out = bitbucket_tool().fn({"op": "issues", "workspace": "ws", "repo_slug": "r"})
    assert "BITBUCKET" in out


def test_bitbucket_issues_renders(monkeypatch):
    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", "tok")
    body = {"values": [
        {"id": 1, "state": "new", "title": "Fix bug"},
    ]}
    _fake_httpx(monkeypatch, get=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.bitbucket_tool import bitbucket_tool
    out = bitbucket_tool().fn({"op": "issues", "workspace": "ws", "repo_slug": "r"})
    assert "Fix bug" in out


# ---------- AWS SES ----------

def _install_fake_boto3_ses(monkeypatch, *, send_id="msg-1",
                            quota=None, verified=None):
    boto3 = types.ModuleType("boto3")

    class _Client:
        def send_email(self, **k):
            return {"MessageId": send_id}

        def get_send_quota(self):
            return quota or {"Max24HourSend": 100, "SentLast24Hours": 5,
                              "MaxSendRate": 1.0}

        def list_verified_email_addresses(self):
            return {"VerifiedEmailAddresses": verified or []}

    boto3.client = lambda *a, **k: _Client()
    monkeypatch.setitem(sys.modules, "boto3", boto3)


def test_ses_requires_op():
    from maverick.tools.ses_tool import ses_tool
    assert "op is required" in ses_tool().fn({})


def test_ses_missing_boto3(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    from maverick.tools.ses_tool import ses_tool
    out = ses_tool().fn({"op": "quota"})
    assert "boto3 not installed" in out


def test_ses_send_dry_run(monkeypatch):
    _install_fake_boto3_ses(monkeypatch)
    from maverick.tools.ses_tool import ses_tool
    out = ses_tool().fn({
        "op": "send", "from_": "no-reply@x", "to": ["a@x"],
        "subject": "hi", "body": "yo",
    })
    assert "DRY RUN" in out


def test_ses_send_confirmed(monkeypatch):
    _install_fake_boto3_ses(monkeypatch, send_id="abc-123")
    from maverick.tools.ses_tool import ses_tool
    out = ses_tool().fn({
        "op": "send", "from_": "no-reply@x", "to": ["a@x"],
        "subject": "hi", "body": "yo", "confirm": True,
    })
    assert "abc-123" in out


def test_ses_quota_renders(monkeypatch):
    _install_fake_boto3_ses(monkeypatch)
    from maverick.tools.ses_tool import ses_tool
    out = ses_tool().fn({"op": "quota"})
    assert "max_24h" in out and "100" in out


# ---------- AWS SNS ----------

def _install_fake_boto3_sns(monkeypatch, *, topics=None, message_id="m-1"):
    boto3 = types.ModuleType("boto3")

    class _Client:
        def list_topics(self):
            return {"Topics": topics or []}

        def publish(self, **k):
            return {"MessageId": message_id}

        def subscribe(self, **k):
            return {"SubscriptionArn": "arn:sub:1"}

        def unsubscribe(self, **k):
            return {}

    boto3.client = lambda *a, **k: _Client()
    monkeypatch.setitem(sys.modules, "boto3", boto3)


def test_sns_requires_op():
    from maverick.tools.sns_tool import sns_tool
    assert "op is required" in sns_tool().fn({})


def test_sns_publish_dry_run(monkeypatch):
    _install_fake_boto3_sns(monkeypatch)
    from maverick.tools.sns_tool import sns_tool
    out = sns_tool().fn({"op": "publish",
                          "topic_arn": "arn:sns:t1", "message": "hi"})
    assert "DRY RUN" in out


def test_sns_publish_confirmed(monkeypatch):
    _install_fake_boto3_sns(monkeypatch, message_id="abc")
    from maverick.tools.sns_tool import sns_tool
    out = sns_tool().fn({
        "op": "publish", "topic_arn": "arn:sns:t1",
        "message": "hi", "confirm": True,
    })
    assert "abc" in out


# ---------- ffmpeg ----------

def test_ffmpeg_requires_op():
    from maverick.tools.ffmpeg_tool import ffmpeg_tool
    assert "op is required" in ffmpeg_tool().fn({})


def test_ffmpeg_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: None)
    from maverick.tools.ffmpeg_tool import ffmpeg_tool
    out = ffmpeg_tool().fn({"op": "convert",
                              "input_path": "/tmp/a.mp4",
                              "output_path": "/tmp/b.mp4"})
    assert "ffmpeg" in out and "PATH" in out


def test_ffmpeg_convert_calls_binary(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/" + b)
    captured = {"cmd": None}

    def _run(cmd, *a, **k):
        captured["cmd"] = cmd
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", _run)
    from maverick.tools.ffmpeg_tool import ffmpeg_tool
    out = ffmpeg_tool().fn({
        "op": "convert", "input_path": "/tmp/a.mp4",
        "output_path": "/tmp/b.mp4",
    })
    assert "wrote /tmp/b.mp4" in out
    assert "ffmpeg" in captured["cmd"][0]


def test_ffmpeg_info_parses_ffprobe(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/" + b)
    import json
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(
            returncode=0,
            stdout=json.dumps({
                "format": {"format_name": "mov,mp4", "duration": "10.0", "bit_rate": "1000"},
                "streams": [{"codec_type": "video", "codec_name": "h264",
                              "width": 1920, "height": 1080}],
            }),
            stderr="",
        ),
    )
    from maverick.tools.ffmpeg_tool import ffmpeg_tool
    out = ffmpeg_tool().fn({"op": "info", "input_path": "/tmp/a.mp4"})
    assert "mov,mp4" in out and "1920x1080" in out


# ---------- pandoc ----------

def test_pandoc_requires_op():
    from maverick.tools.pandoc_tool import pandoc_tool
    assert "op is required" in pandoc_tool().fn({})


def test_pandoc_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: None)
    from maverick.tools.pandoc_tool import pandoc_tool
    out = pandoc_tool().fn({"op": "convert",
                              "input_path": "/x", "output_path": "/y"})
    assert "pandoc" in out and "PATH" in out


def test_pandoc_markdown_to_html(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/pandoc")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(
            returncode=0, stdout="<p>Hello</p>\n", stderr="",
        ),
    )
    from maverick.tools.pandoc_tool import pandoc_tool
    out = pandoc_tool().fn({"op": "markdown_to_html", "text": "Hello"})
    assert "<p>Hello</p>" in out


# ---------- ImageMagick ----------

def test_imagemagick_requires_op():
    from maverick.tools.imagemagick_tool import imagemagick_tool
    assert "op is required" in imagemagick_tool().fn({})


def test_imagemagick_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: None)
    from maverick.tools.imagemagick_tool import imagemagick_tool
    out = imagemagick_tool().fn({"op": "resize",
                                   "input_path": "a.png",
                                   "output_path": "b.png"})
    assert "ImageMagick" in out


def test_imagemagick_resize(monkeypatch):
    monkeypatch.setattr("shutil.which",
                        lambda b: "/usr/bin/magick" if b == "magick" else None)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout="", stderr=""),
    )
    from maverick.tools.imagemagick_tool import imagemagick_tool
    out = imagemagick_tool().fn({
        "op": "resize", "input_path": "/tmp/a.png",
        "output_path": "/tmp/b.png", "width": 800,
    })
    assert "wrote /tmp/b.png" in out and "800" in out


def test_imagemagick_identify_parses(monkeypatch):
    monkeypatch.setattr("shutil.which",
                        lambda b: "/usr/bin/magick" if b == "magick" else None)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(
            returncode=0, stdout="1024 768 PNG 200KB image.png\n", stderr="",
        ),
    )
    from maverick.tools.imagemagick_tool import imagemagick_tool
    out = imagemagick_tool().fn({"op": "identify", "input_path": "/tmp/a.png"})
    assert "1024x768" in out and "PNG" in out


# ---------- GA4 ----------

def test_ga4_requires_op():
    from maverick.tools.ga4_tool import ga4_tool
    assert "op is required" in ga4_tool().fn({})


def test_ga4_send_event_requires_keys(monkeypatch):
    monkeypatch.delenv("GA4_MEASUREMENT_ID", raising=False)
    monkeypatch.delenv("GA4_API_SECRET", raising=False)
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.ga4_tool import ga4_tool
    out = ga4_tool().fn({"op": "send_event",
                          "client_id": "u", "name": "signup"})
    assert "GA4_MEASUREMENT_ID" in out


def test_ga4_send_event_posts(monkeypatch):
    monkeypatch.setenv("GA4_MEASUREMENT_ID", "G-XX")
    monkeypatch.setenv("GA4_API_SECRET", "sec")
    _fake_httpx(monkeypatch,
                post=MagicMock(return_value=_resp(204, "")))
    from maverick.tools.ga4_tool import ga4_tool
    out = ga4_tool().fn({
        "op": "send_event", "client_id": "u", "name": "signup",
        "params": {"value": 1},
    })
    assert "accepted" in out


def test_ga4_run_report_requires_keys(monkeypatch):
    monkeypatch.delenv("GA4_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GA4_PROPERTY_ID", raising=False)
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.ga4_tool import ga4_tool
    out = ga4_tool().fn({"op": "run_report"})
    assert "GA4_ACCESS_TOKEN" in out


# ---------- Plaid ----------

def test_plaid_requires_op():
    from maverick.tools.plaid_tool import plaid_tool
    assert "op is required" in plaid_tool().fn({})


def test_plaid_requires_access_token():
    from maverick.tools.plaid_tool import plaid_tool
    out = plaid_tool().fn({"op": "accounts"})
    assert "access_token" in out


def test_plaid_missing_secrets(monkeypatch):
    monkeypatch.delenv("PLAID_CLIENT_ID", raising=False)
    monkeypatch.delenv("PLAID_SECRET", raising=False)
    _fake_httpx(monkeypatch, post=MagicMock())
    from maverick.tools.plaid_tool import plaid_tool
    out = plaid_tool().fn({"op": "accounts", "access_token": "tok"})
    assert "PLAID_CLIENT_ID" in out


def test_plaid_accounts_renders(monkeypatch):
    monkeypatch.setenv("PLAID_CLIENT_ID", "id")
    monkeypatch.setenv("PLAID_SECRET", "sec")
    body = {"accounts": [{
        "account_id": "acc123abc", "name": "Checking",
        "type": "depository", "subtype": "checking",
        "balances": {"current": 1234.56, "iso_currency_code": "USD"},
    }]}
    _fake_httpx(monkeypatch,
                post=MagicMock(return_value=_resp(200, body)))
    from maverick.tools.plaid_tool import plaid_tool
    out = plaid_tool().fn({"op": "accounts", "access_token": "tok"})
    assert "Checking" in out and "1,234.56" in out


# ---------- Workflow engine ----------

def test_workflow_runs_simple_dag():
    from unittest.mock import MagicMock
    from maverick.workflow import Step, Workflow

    reg = MagicMock()
    outputs = iter(["A-out", "B-out", "C-out"])

    async def _run(name, args):
        return next(outputs)

    reg.run = _run
    wf = Workflow(steps=[
        Step("a", "toolA", {"x": 1}),
        Step("b", "toolB", {"x": "${a.out}"}),
        Step("c", "toolC", {"x": "${b.out}", "y": "${a.out}"}),
    ])
    res = wf.run(reg)
    assert [s.name for s in res.steps] == ["a", "b", "c"]
    assert res.steps[1].output == "B-out"
    # placeholders were resolved
    # (we can't see them directly via reg here; just confirm no failures)
    assert not res.failed


def test_workflow_stops_on_error():
    from maverick.workflow import Step, Workflow

    class _Reg:
        async def run(self, name, args):
            if name == "boom":
                return "ERROR: nope"
            return "ok"

    wf = Workflow(steps=[
        Step("a", "ok-tool"),
        Step("b", "boom"),
        Step("c", "ok-tool", depends_on=["b"]),
    ])
    res = wf.run(_Reg())
    assert res.failed
    # Should run a + b only, not c.
    assert [s.name for s in res.steps] == ["a", "b"]


def test_workflow_rejects_cycle():
    from maverick.workflow import Step, Workflow, WorkflowCycle
    try:
        Workflow(steps=[
            Step("a", "x", depends_on=["b"]),
            Step("b", "x", depends_on=["a"]),
        ])
    except WorkflowCycle:
        return
    raise AssertionError("expected WorkflowCycle")


def test_workflow_rejects_self_dep():
    from maverick.workflow import Step, Workflow, WorkflowCycle
    try:
        Workflow(steps=[Step("a", "x", depends_on=["a"])])
    except WorkflowCycle:
        return
    raise AssertionError("expected WorkflowCycle")


def test_workflow_rejects_unknown_dep():
    from maverick.workflow import Step, Workflow
    try:
        Workflow(steps=[Step("a", "x", {"y": "${nope.out}"})])
    except ValueError as e:
        assert "unknown dependency" in str(e)
        return
    raise AssertionError("expected ValueError")


def test_workflow_resolves_string_placeholders():
    from maverick.workflow import Step, Workflow

    seen: list[dict] = []

    class _Reg:
        async def run(self, name, args):
            seen.append(args)
            return "first-output"

    wf = Workflow(steps=[
        Step("first", "echo", {"msg": "hi"}),
        Step("second", "echo",
             {"prefix": "got: ${first.out}!", "n": 1}),
    ])
    wf.run(_Reg())
    assert seen[1]["prefix"] == "got: first-output!"
    assert seen[1]["n"] == 1


# ---------- registration smoke ----------

def test_new_tools_register(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    expected = (
        "plausible", "mixpanel", "calendly", "zoom", "spotify",
        "home_assistant", "reddit", "bitbucket", "ses", "sns",
        "ffmpeg", "pandoc", "imagemagick", "ga4", "plaid",
    )
    missing = [n for n in expected if n not in names]
    assert not missing, f"unregistered: {missing}"
