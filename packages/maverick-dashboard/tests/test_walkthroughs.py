"""Video walkthroughs: artifact listing, media serving, and the export
endpoint over the real replay-to-MP4 machinery (render itself is stubbed —
the encode needs Pillow + ffmpeg and is covered by core's replay tests)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "mvhome"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    return tmp_path / "mvhome"


@pytest.fixture
def world(home, tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    w = world_model.WorldModel(tmp_path / "world.db")
    yield w
    w.close()


@pytest.fixture
def client(world, monkeypatch):
    from maverick_dashboard import api as api_mod
    from maverick_dashboard import app as app_mod
    monkeypatch.setattr(app_mod, "_world", lambda: world)
    monkeypatch.setattr(api_mod, "_world", lambda: world)
    return TestClient(app_mod.app, headers={"Origin": "http://testserver"})


def test_page_empty_state_is_honest(client, home):
    r = client.get("/walkthroughs")
    assert r.status_code == 200
    assert "No walkthroughs exported yet" in r.text
    # the real export path + where artifacts land
    assert "/api/v1/goals/" in r.text and "/walkthrough" in r.text
    assert str(home / "walkthroughs") in r.text
    # no fake thumbnails / placeholder videos
    assert "<video" not in r.text


def test_page_lists_artifacts_with_video_and_captions(client, home):
    d = home / "walkthroughs"
    d.mkdir(parents=True)
    (d / "goal-7.mp4").write_bytes(b"\x00\x00fake")
    (d / "goal-7.vtt").write_text("WEBVTT\n")
    (d / "freeform.mp4").write_bytes(b"\x00")  # non goal-N name: still listed
    r = client.get("/walkthroughs")
    assert r.status_code == 200
    assert "<video controls" in r.text
    assert 'src="/walkthroughs/media/goal-7.mp4"' in r.text
    assert '<track kind="captions" src="/walkthroughs/media/goal-7.vtt"' in r.text
    # goal-N names link to the run's tutorial export
    assert "/api/v1/goals/7/tutorial.md" in r.text
    assert 'src="/walkthroughs/media/freeform.mp4"' in r.text


def test_media_route_serves_and_guards(client, home):
    d = home / "walkthroughs"
    d.mkdir(parents=True)
    (d / "goal-3.mp4").write_bytes(b"MP4DATA")
    (d / "goal-3.vtt").write_text("WEBVTT\n")
    (home / "secret.txt").write_text("nope")

    r = client.get("/walkthroughs/media/goal-3.mp4")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/mp4")
    assert r.content == b"MP4DATA"
    r = client.get("/walkthroughs/media/goal-3.vtt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/vtt")
    # unknown artifact
    assert client.get("/walkthroughs/media/goal-99.mp4").status_code == 404
    # %2f-encoded traversal never matches the route (the path param cannot
    # span "/"), and names that do reach the handler are pattern-gated.
    assert client.get("/walkthroughs/media/..%2fsecret.txt").status_code == 404
    assert client.get("/walkthroughs/media/secret.txt").status_code == 400
    assert client.get("/walkthroughs/media/..mp4").status_code in (400, 404)


def test_export_missing_goal_404(client):
    r = client.post("/api/v1/goals/99999/walkthrough")
    assert r.status_code == 404


def test_export_without_events_400(client, world):
    gid = world.create_goal("never ran", "")
    r = client.post(f"/api/v1/goals/{gid}/walkthrough")
    assert r.status_code == 400
    assert "no events recorded" in r.json()["detail"]


@pytest.fixture
def render_stub(monkeypatch):
    """Stub maverick.replay_video.render (the encode half needs ffmpeg)."""
    from maverick import replay_video
    calls = []

    def fake_render(goal_id, out_path, *, sandbox=None, events=None, fps=25):
        out_path.write_bytes(b"\x00fakemp4")
        calls.append({"goal_id": goal_id, "out_path": out_path,
                      "events": events})
        return SimpleNamespace(
            frames=len(events or []), frame_dir=out_path.parent,
            concat_path=out_path.parent / "frames.ffconcat",
            command=["ffmpeg", "-y"], encoded=True, detail="stub encode",
        )

    monkeypatch.setattr(replay_video, "render", fake_render)
    return calls


def test_export_writes_video_and_captions(client, world, home, render_stub):
    gid = world.create_goal("ran fine", "")
    world.append_event(gid, "planner", "plan", "step one then step two")
    world.append_event(gid, "worker", "observation", "did the thing")
    r = client.post(f"/api/v1/goals/{gid}/walkthrough")
    assert r.status_code == 201
    body = r.json()
    assert body["encoded"] is True
    assert body["frames"] == 2
    assert body["video"] == f"goal-{gid}.mp4"
    assert body["captions"] == f"goal-{gid}.vtt"
    # render got the run's real events, into the walkthroughs dir
    assert render_stub[0]["out_path"] == home / "walkthroughs" / f"goal-{gid}.mp4"
    assert [e["kind"] for e in render_stub[0]["events"]] == ["plan", "observation"]
    # the captions track is real WebVTT derived from the storyboard
    vtt = (home / "walkthroughs" / f"goal-{gid}.vtt").read_text()
    assert vtt.startswith("WEBVTT")
    assert "-->" in vtt
    assert "00:00:00.000" in vtt
    # the page now lists it
    page = client.get("/walkthroughs").text
    assert f'src="/walkthroughs/media/goal-{gid}.mp4"' in page


def test_export_reports_unencoded_honestly(client, world, monkeypatch):
    """No Pillow/ffmpeg -> encoded=false, no video name, command included."""
    from maverick import replay_video
    def fake_render(goal_id, out_path, *, sandbox=None, events=None, fps=25):
        return SimpleNamespace(
            frames=len(events or []), frame_dir=out_path.parent,
            concat_path=out_path.parent / "frames.ffconcat",
            command=["ffmpeg", "-y", "out.mp4"], encoded=False,
            detail="Pillow not installed; wrote frame manifest",
        )
    monkeypatch.setattr(replay_video, "render", fake_render)
    gid = world.create_goal("ran", "")
    world.append_event(gid, "a", "plan", "x")
    body = client.post(f"/api/v1/goals/{gid}/walkthrough").json()
    assert body["encoded"] is False
    assert body["video"] is None
    assert body["ffmpeg_command"][0] == "ffmpeg"
    assert "Pillow" in body["detail"]
