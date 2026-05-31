"""File + image attachment storage."""
from __future__ import annotations

import pytest
from maverick.attachments import (
    MAX_FILE_BYTES,
    MAX_GOAL_BYTES,
    AttachmentRejected,
    content_blocks_for_goal,
    store,
)
from maverick.world_model import WorldModel


def test_store_text_writes_to_disk(tmp_path):
    data = b"hello world\n"
    out = store(
        goal_id=42,
        filename="notes.txt",
        mime="text/plain",
        data=data,
        root=tmp_path,
    )
    assert out.filename == "notes.txt"
    assert out.mime == "text/plain"
    assert out.size_bytes == len(data)
    assert out.path.exists()
    assert out.path.read_bytes() == data
    # sha-prefixed dest avoids name collisions.
    assert out.path.name.startswith(out.sha256[:16] + "-")


def test_store_rejects_unknown_mime(tmp_path):
    with pytest.raises(AttachmentRejected, match="mime type not allowed"):
        store(
            goal_id=1, filename="malware.exe",
            mime="application/x-msdownload", data=b"MZ\x00",
            root=tmp_path,
        )


def test_store_rejects_empty(tmp_path):
    with pytest.raises(AttachmentRejected, match="empty file"):
        store(
            goal_id=1, filename="empty.txt",
            mime="text/plain", data=b"", root=tmp_path,
        )


def test_store_rejects_oversized(tmp_path):
    with pytest.raises(AttachmentRejected, match="file too large"):
        store(
            goal_id=1, filename="big.txt",
            mime="text/plain",
            data=b"x" * (MAX_FILE_BYTES + 1),
            root=tmp_path,
        )


def test_store_rejects_path_traversal(tmp_path):
    with pytest.raises(AttachmentRejected, match="invalid filename"):
        store(
            goal_id=1, filename="../escape.txt",
            mime="text/plain", data=b"x", root=tmp_path,
        )


def test_store_enforces_per_goal_quota(tmp_path):
    # Filling 90% of quota then trying to add more than 10% must reject.
    near_full = MAX_GOAL_BYTES - 100
    with pytest.raises(AttachmentRejected, match="quota exceeded"):
        store(
            goal_id=1, filename="x.txt", mime="text/plain",
            data=b"x" * 1000,
            existing_total=near_full,
            root=tmp_path,
        )


def test_world_model_persists_attachment(tmp_path):
    wm = WorldModel(path=tmp_path / "w.db")
    gid = wm.create_goal("test", "")
    out = store(
        goal_id=gid, filename="hi.txt", mime="text/plain",
        data=b"hi", root=tmp_path / "attach",
    )
    aid = wm.add_attachment(
        goal_id=gid, filename=out.filename, mime=out.mime,
        size_bytes=out.size_bytes, sha256=out.sha256, path=str(out.path),
    )
    assert aid > 0

    attachments = wm.list_attachments(gid)
    assert len(attachments) == 1
    assert attachments[0].filename == "hi.txt"
    assert attachments[0].sha256 == out.sha256


def test_image_attachments_become_vision_blocks(tmp_path):
    # 1x1 PNG transparent pixel, minimal valid bytes
    png_bytes = bytes.fromhex(
        "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4"
        "890000000A49444154789C6300010000000500010D0A2DB40000000049454E44"
        "AE426082"
    )
    wm = WorldModel(path=tmp_path / "w.db")
    gid = wm.create_goal("vision", "")
    out = store(
        goal_id=gid, filename="pixel.png", mime="image/png",
        data=png_bytes, root=tmp_path / "attach",
    )
    wm.add_attachment(
        goal_id=gid, filename=out.filename, mime=out.mime,
        size_bytes=out.size_bytes, sha256=out.sha256, path=str(out.path),
    )

    blocks = content_blocks_for_goal(wm, gid)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["type"] == "base64"
    assert blocks[0]["source"]["media_type"] == "image/png"
    assert blocks[0]["source"]["data"]


def test_text_attachment_is_not_vision_block(tmp_path):
    wm = WorldModel(path=tmp_path / "w.db")
    gid = wm.create_goal("textonly", "")
    out = store(
        goal_id=gid, filename="hi.txt", mime="text/plain",
        data=b"hi", root=tmp_path / "attach",
    )
    wm.add_attachment(
        goal_id=gid, filename=out.filename, mime=out.mime,
        size_bytes=out.size_bytes, sha256=out.sha256, path=str(out.path),
    )
    # Text attachments are reachable via list_attachments + read_file,
    # not auto-embedded.
    blocks = content_blocks_for_goal(wm, gid)
    assert blocks == []


def test_list_attachments_tool_returns_metadata(tmp_path):
    from maverick.tools.attachments import list_attachments_tool

    wm = WorldModel(path=tmp_path / "w.db")
    gid = wm.create_goal("attached", "")
    out = store(
        goal_id=gid, filename="a.txt", mime="text/plain",
        data=b"a", root=tmp_path / "attach",
    )
    wm.add_attachment(
        goal_id=gid, filename=out.filename, mime=out.mime,
        size_bytes=out.size_bytes, sha256=out.sha256, path=str(out.path),
    )
    tool = list_attachments_tool(wm, gid)
    result = tool.fn({})
    assert "a.txt" in result
    assert "text/plain" in result


def test_list_attachments_tool_no_goal(tmp_path):
    """The tool returns a friendly stub when there's no goal context."""
    from maverick.tools.attachments import list_attachments_tool
    wm = WorldModel(path=tmp_path / "w.db")
    tool = list_attachments_tool(wm, None)
    assert "no goal context" in tool.fn({})
