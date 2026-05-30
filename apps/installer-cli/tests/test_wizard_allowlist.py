"""The wizard must collect the per-sender allowlist that channels require.

Regression for the launch-audit HIGH: discord/telegram/slack/signal/matrix/
email/bluesky/mastodon raise ValueError without an allowlist, but the wizard
never prompted for one, so a wizard-only setup produced channels that silently
failed to start (server.py logs + continues). pick_channels now collects it.
"""
from __future__ import annotations


def test_pick_channels_collects_discord_allowlist(monkeypatch):
    from maverick_installer import wizard

    monkeypatch.setattr(wizard, "_q_checkbox", lambda msg, choices: ["discord  - Discord"])
    # discord's only _q_text prompt is the allowlist.
    monkeypatch.setattr(wizard, "_q_text", lambda msg, default="": "111, 222")

    channels, _ = wizard.pick_channels("vps")
    assert channels["discord"]["allowed_user_ids"] == ["111", "222"]


def test_pick_channels_voice_collects_optional_callers(monkeypatch):
    from maverick_installer import wizard

    monkeypatch.setattr(wizard, "_q_checkbox", lambda msg, choices: ["voice  - Voice"])
    # voice prompts: phone_number, assistant_id, provider, port, allowed_callers.
    answers = iter(["", "", "vapi", "8770", "+12025550111"])
    monkeypatch.setattr(wizard, "_q_text", lambda msg, default="": next(answers))

    channels, _ = wizard.pick_channels("vps")
    assert channels["voice"]["allowed_callers"] == ["+12025550111"]


def test_pick_channels_no_allowlist_channel_unaffected(monkeypatch):
    """imessage has no allowlist requirement -> no allowed_user_ids key added."""
    from maverick_installer import wizard

    monkeypatch.setattr(wizard, "_q_checkbox", lambda msg, choices: ["imessage  - iMessage"])
    monkeypatch.setattr(wizard, "_q_text", lambda msg, default="": "")

    channels, _ = wizard.pick_channels("vps")
    assert "allowed_user_ids" not in channels["imessage"]
    assert channels["imessage"]["enabled"] is True
