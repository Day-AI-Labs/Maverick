"""OTel GenAI semantic-convention attributes for LLM spans.

Maverick already had opt-in OTel/Prometheus, but the LLM spans used ad-hoc
attribute names and a generic span name that no OTel-aware backend
understands without custom mapping. observability.gen_ai_attributes() /
gen_ai_span_name() emit the standard gen_ai.* names so traces are legible to
Grafana / Honeycomb / Arize Phoenix out of the box, and LLM.complete /
complete_async name their span via the convention.
"""
from __future__ import annotations

import inspect

from maverick import llm as llm_mod
from maverick import observability as obs


def test_span_name_is_operation_space_model():
    assert obs.gen_ai_span_name("chat", "claude-opus-4-8") == "chat claude-opus-4-8"


def test_request_attributes_use_genai_semconv_keys():
    a = obs.gen_ai_attributes("anthropic", "claude-opus-4-8", max_tokens=4096)
    assert a["gen_ai.operation.name"] == "chat"
    assert a["gen_ai.system"] == "anthropic"
    assert a["gen_ai.request.model"] == "claude-opus-4-8"
    assert a["gen_ai.request.max_tokens"] == 4096
    # response/usage fields omitted when unknown (built in a second pass).
    assert "gen_ai.usage.input_tokens" not in a


def test_usage_attributes_included_when_provided():
    a = obs.gen_ai_attributes(
        "openai", "gpt-5.5", operation="chat",
        response_model="gpt-5.5", input_tokens=1200, output_tokens=340,
    )
    assert a["gen_ai.response.model"] == "gpt-5.5"
    assert a["gen_ai.usage.input_tokens"] == 1200
    assert a["gen_ai.usage.output_tokens"] == 340


def test_exports():
    assert "gen_ai_attributes" in obs.__all__
    assert "gen_ai_span_name" in obs.__all__


def test_llm_complete_paths_use_genai_span_helpers():
    """Both the sync and async LLM entry points must name their OTel span via
    the GenAI convention (gen_ai_span_name) and attach gen_ai_attributes --
    not the old generic 'llm.complete' span. Source-level guard so it can't
    silently regress to ad-hoc attribute names."""
    src = inspect.getsource(llm_mod.LLM.complete)
    src += inspect.getsource(llm_mod.LLM.complete_async)
    assert "gen_ai_span_name(" in src
    assert "gen_ai_attributes(" in src
    # the old generic span name must be gone from both paths
    assert '"llm.complete"' not in src
