"""Importing external automations (n8n/Make/...) into Lightwork primitives.

Covers the IR rendering, the n8n translator (pure, fixture-driven), the
registry, the feature gate, and materialization onto a user Template + a
schedule. No network: ``fetch`` is not exercised here (it's the thin API layer);
``translate`` is the logic under test.
"""
from __future__ import annotations

import pytest
from maverick import automation_import as ai
from maverick.automation_import import ir, n8n

# --- fixtures: realistic n8n workflow JSON ---------------------------------

WEBHOOK_WORKFLOW = {
    "id": "42",
    "name": "New lead → Slack + CRM",
    "active": True,
    "nodes": [
        {"name": "Incoming Webhook", "type": "n8n-nodes-base.webhook",
         "parameters": {"path": "lead", "httpMethod": "POST"}},
        {"name": "Post to Slack", "type": "n8n-nodes-base.slack",
         "parameters": {"resource": "message", "operation": "post",
                        "channel": "#sales", "text": "New lead!"}},
        {"name": "Create CRM contact", "type": "n8n-nodes-base.hubspot",
         "parameters": {"resource": "contact", "operation": "create"}},
    ],
    "connections": {
        "Incoming Webhook": {"main": [[{"node": "Post to Slack", "type": "main", "index": 0}]]},
        "Post to Slack": {"main": [[{"node": "Create CRM contact", "type": "main", "index": 0}]]},
    },
}

CRON_WORKFLOW = {
    "id": "7",
    "name": "Daily digest",
    "active": True,
    "nodes": [
        {"name": "Every morning", "type": "n8n-nodes-base.cron",
         "parameters": {"cronExpression": "0 9 * * *"}},
        {"name": "Send email", "type": "n8n-nodes-base.emailSend",
         "parameters": {"operation": "send"}},
    ],
    "connections": {
        "Every morning": {"main": [[{"node": "Send email", "type": "main", "index": 0}]]},
    },
}


class TestN8nTranslate:
    def test_webhook_workflow_steps_in_execution_order(self):
        a = n8n.translate(WEBHOOK_WORKFLOW)
        assert a.source == "n8n"
        assert a.source_id == "42"
        assert a.trigger.kind == ir.TRIGGER_WEBHOOK
        # Steps follow the connection graph, not the (here identical) array order.
        assert [s.name for s in a.steps] == ["Post to Slack", "Create CRM contact"]
        assert a.steps[0].app == "slack"
        assert a.steps[0].operation in ("post", "message")
        assert a.steps[1].app == "hubspot"
        assert "slack" in a.tool_hints() and "hubspot" in a.tool_hints()

    def test_disconnected_node_still_included(self):
        wf = {
            "id": "9", "name": "branchy",
            "nodes": [
                {"name": "Manual", "type": "n8n-nodes-base.manualTrigger", "parameters": {}},
                {"name": "Wired", "type": "n8n-nodes-base.set", "parameters": {}},
                {"name": "Orphan", "type": "n8n-nodes-base.noOp", "parameters": {}},
            ],
            "connections": {"Manual": {"main": [[{"node": "Wired"}]]}},
        }
        a = n8n.translate(wf)
        names = [s.name for s in a.steps]
        assert "Wired" in names and "Orphan" in names  # orphan appended, not dropped
        assert a.trigger.kind == ir.TRIGGER_MANUAL

    def test_cron_trigger_recovers_expression(self):
        a = n8n.translate(CRON_WORKFLOW)
        assert a.trigger.kind == ir.TRIGGER_SCHEDULE
        assert a.trigger.cron == "0 9 * * *"
        assert [s.name for s in a.steps] == ["Send email"]

    def test_schedule_rule_expression(self):
        wf = {
            "id": "1", "name": "ruled",
            "nodes": [
                {"name": "Sched", "type": "n8n-nodes-base.scheduleTrigger",
                 "parameters": {"rule": {"interval": [{"cronExpression": "*/5 * * * *"}]}}},
                {"name": "Do", "type": "n8n-nodes-base.set", "parameters": {}},
            ],
            "connections": {"Sched": {"main": [[{"node": "Do"}]]}},
        }
        a = n8n.translate(wf)
        assert a.trigger.kind == ir.TRIGGER_SCHEDULE
        assert a.trigger.cron == "*/5 * * * *"

    def test_app_trigger_is_event(self):
        wf = {
            "id": "2", "name": "gmailish",
            "nodes": [
                {"name": "Gmail Trigger", "type": "n8n-nodes-base.gmailTrigger", "parameters": {}},
                {"name": "Reply", "type": "n8n-nodes-base.gmail", "parameters": {"operation": "reply"}},
            ],
            "connections": {"Gmail Trigger": {"main": [[{"node": "Reply"}]]}},
        }
        a = n8n.translate(wf)
        assert a.trigger.kind == ir.TRIGGER_EVENT
        assert a.trigger.event == "gmailTrigger"

    def test_bad_input_raises(self):
        with pytest.raises(ai.ImporterError):
            n8n.translate({"name": "no nodes"})
        with pytest.raises(ai.ImporterError):
            n8n.translate("not a dict")  # type: ignore[arg-type]


class TestIR:
    def test_render_body_is_runnable_brief(self):
        a = n8n.translate(WEBHOOK_WORKFLOW)
        title, body = a.render()
        assert "imported from n8n" in title
        assert "Imported from n8n" in body
        assert "1." in body and "2." in body          # numbered actions
        assert "FINAL:" in body                         # closes like a goal brief
        assert "inbound webhook" in body.lower()        # trigger context

    def test_template_name_is_a_slug(self):
        a = n8n.translate(WEBHOOK_WORKFLOW)
        name = a.template_name()
        assert name == "n8n-new-lead-slack-crm"
        assert all(c.isalnum() or c == "-" for c in name)

    def test_unknown_trigger_kind_falls_back_to_event(self):
        t = ir.ImportedTrigger(kind="bogus")
        assert t.kind == ir.TRIGGER_EVENT


class TestRegistry:
    def test_n8n_registered(self):
        assert "n8n" in ai.available_sources()
        assert ai.get_importer("n8n").can_fetch_definitions is True

    def test_unknown_source_raises(self):
        with pytest.raises(ai.ImporterError):
            ai.get_importer("does-not-exist")

    def test_translate_all_skips_bad(self):
        out = ai.translate_all("n8n", [WEBHOOK_WORKFLOW, {"bad": 1}, CRON_WORKFLOW])
        assert [a.name for a in out] == ["New lead → Slack + CRM", "Daily digest"]


class TestEnabled:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_AUTOMATION_IMPORT", raising=False)
        assert ai.enabled() is False

    def test_env_override_on(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_AUTOMATION_IMPORT", "1")
        assert ai.enabled() is True


class _FakeQueue:
    def __init__(self):
        self.enqueued: list[tuple] = []

    def enqueue(self, kind, payload, run_at=None):
        self.enqueued.append((kind, payload, run_at))
        return len(self.enqueued)


class TestMaterialize:
    @pytest.fixture(autouse=True)
    def _isolate_templates(self, tmp_path, monkeypatch):
        import maverick.templates as t
        monkeypatch.setattr(t, "USER_TEMPLATES", tmp_path / "templates")

    def test_webhook_automation_creates_template_and_suggests_trigger(self):
        a = n8n.translate(WEBHOOK_WORKFLOW)
        res = ai.materialize(a)
        assert res.created_template is True
        assert res.template_name == "n8n-new-lead-slack-crm"
        assert res.suggested_trigger == {
            "kind": "webhook", "template": res.template_name, "name": res.template_name,
        }
        # The template is loadable and renders a goal.
        from maverick.templates import load_template
        tpl = load_template(res.template_name)
        assert tpl is not None
        rt_title, rt_body = tpl.render()
        assert "Post to Slack" in rt_body

    def test_schedule_automation_with_queue_creates_schedule(self):
        a = n8n.translate(CRON_WORKFLOW)
        q = _FakeQueue()
        res = ai.materialize(a, queue=q)
        assert res.schedule is not None
        assert res.schedule["cron"] == "0 9 * * *"
        assert q.enqueued and q.enqueued[0][0] == "start_goal"
        payload = q.enqueued[0][1]
        # The worker's start_goal handler mints a goal from a non-empty "text";
        # a {"template": ...} payload (no text) would fail at run time. The
        # payload must match the dashboard /api/v1/schedules shape.
        assert payload["text"] and "Send email" in payload["text"]
        assert payload["title"]
        assert payload["__cron__"] == "0 9 * * *"
        assert payload["schedule_id"]
        assert "template" not in payload  # snapshot the brief, not a template ref

    def test_scheduled_payload_satisfies_worker_contract(self):
        # Regression: feed the enqueued payload straight to the worker's
        # start_goal validation so an empty-text payload can't slip back in.
        a = n8n.translate(CRON_WORKFLOW)
        q = _FakeQueue()
        ai.materialize(a, queue=q)
        payload = q.enqueued[0][1]
        assert (payload.get("text") or "").strip(), "worker rejects empty text"

    def test_schedule_without_queue_suggests_it(self):
        a = n8n.translate(CRON_WORKFLOW)
        res = ai.materialize(a)  # no queue
        assert res.schedule is None
        assert res.suggested_trigger == {
            "kind": "schedule", "cron": "0 9 * * *", "template": res.template_name,
        }

    def test_save_false_skips_write(self):
        a = n8n.translate(WEBHOOK_WORKFLOW)
        res = ai.materialize(a, save=False)
        assert res.created_template is False
        from maverick.templates import load_template
        with pytest.raises(FileNotFoundError):
            load_template(res.template_name)
