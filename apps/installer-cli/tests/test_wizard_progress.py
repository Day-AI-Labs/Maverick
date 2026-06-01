"""Progress-bar UX for the advanced wizard flow: ordered STEPS list,
the _step_indicator formatter, and the Step N/M lines surfacing in run()."""
from __future__ import annotations

# ---------- STEPS list ----------

def test_steps_list_is_ordered_and_unique():
    from maverick_installer import wizard
    assert len(wizard.STEPS) == 22
    keys = [k for k, _ in wizard.STEPS]
    assert keys[0] == "deployment"
    assert keys[-1] == "a2a"
    assert len(set(keys)) == len(keys)  # no dupes


# ---------- _step_indicator ----------

def test_step_indicator_formats_step_n_of_m():
    from maverick_installer import wizard
    out = wizard._step_indicator(3)
    assert "Step 3/22" in out
    assert wizard.STEPS[2][1] in out  # the label


def test_step_indicator_includes_breadcrumb_of_done_labels():
    from maverick_installer import wizard
    out = wizard._step_indicator(3, done=["Deployment", "Providers"])
    assert "Step 3/22" in out
    assert "Deployment" in out
    assert "Providers" in out


def test_step_indicator_no_breadcrumb_when_done_empty():
    from maverick_installer import wizard
    out = wizard._step_indicator(1, done=[])
    assert "Step 1/22" in out
    assert "›" not in out


# ---------- indicator surfaces in run() ----------

def test_run_prints_step_indicators(monkeypatch):
    import io

    from maverick_installer import wizard
    from rich.console import Console

    # Use a no-color console so Rich doesn't fragment "Step N/M" with
    # inline ANSI codes, which would break the substring assertions.
    monkeypatch.setattr(
        wizard, "console",
        Console(file=io.StringIO(), force_terminal=False, no_color=True),
    )

    # Present an interactive stdin so run()'s non-TTY guard doesn't
    # short-circuit the prompt flow under pytest.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    # Skip the mode picker / consumer branch and preflight.
    monkeypatch.setattr(wizard, "pick_mode", lambda: "advanced")
    monkeypatch.setattr(wizard, "preflight", lambda: True)

    # Stub every pick_* with a benign return matching its shape.
    monkeypatch.setattr(wizard, "pick_deployment", lambda: "desktop")
    monkeypatch.setattr(wizard, "pick_providers", lambda: ["anthropic"])
    monkeypatch.setattr(wizard, "pick_models_per_role", lambda providers: {})
    monkeypatch.setattr(wizard, "pick_channels", lambda deployment: ({}, set()))
    monkeypatch.setattr(wizard, "pick_safety", lambda: {})
    monkeypatch.setattr(wizard, "pick_signed_skills", lambda: {})
    monkeypatch.setattr(wizard, "pick_budget", lambda: {})
    monkeypatch.setattr(wizard, "pick_sandbox", lambda: {})
    monkeypatch.setattr(wizard, "pick_capabilities", lambda: {})
    monkeypatch.setattr(wizard, "pick_advanced", lambda: {})
    monkeypatch.setattr(wizard, "pick_web_search", lambda: (False, []))
    monkeypatch.setattr(wizard, "pick_mcp_servers", lambda: {})
    monkeypatch.setattr(wizard, "pick_plugins", lambda: [])
    monkeypatch.setattr(wizard, "pick_tool_acl", lambda channels: {})
    monkeypatch.setattr(wizard, "pick_rate_limits", lambda channels: {})
    monkeypatch.setattr(wizard, "pick_retention", lambda: {})
    monkeypatch.setattr(wizard, "pick_persona", lambda: {})
    monkeypatch.setattr(wizard, "pick_notifications", lambda: ({}, []))
    monkeypatch.setattr(wizard, "pick_webhooks", lambda: ({}, []))
    monkeypatch.setattr(wizard, "pick_a2a", lambda: ({}, []))

    # Avoid touching disk / network past the prompt loop.
    monkeypatch.setattr(wizard, "_save_partial", lambda state: None)
    monkeypatch.setattr(wizard, "collect_api_keys", lambda providers, envs: {})
    monkeypatch.setattr(wizard, "collect_browser_sessions", lambda providers: {})
    # Decline the final "write config and finish?" so we stop cleanly
    # right after the prompt loop, before write_config / smoke_test.
    monkeypatch.setattr(wizard, "_q_confirm", lambda *a, **kw: False)

    rc = wizard.run()
    assert rc == 0

    out = wizard.console.file.getvalue()
    assert "Step 1/22" in out
    assert "Step 3/22" in out
    assert "Step 22/22" in out
    # Breadcrumb of earlier answers trails later steps.
    assert "Deployment" in out
