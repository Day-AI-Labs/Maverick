"""OTLP endpoint/headers config + OTel GenAI semconv for tool spans.

Extends the existing opt-in OTel layer (test_genai_semconv.py covers the LLM
helpers). Here we assert:

  - ``MAVERICK_OTEL_HEADERS`` is parsed from the env into the exporter, and the
    no-header default path is unchanged;
  - enabling stays opt-in / no-op by default (otel off);
  - tool spans get the standard ``execute_tool`` gen_ai.* attributes.

Hermetic: no network, no live collector. Tests that need a real tracer skip
gracefully when opentelemetry isn't importable, like the repo's other
otel-dependent tests.
"""
from __future__ import annotations

import importlib

import pytest
from maverick import observability as obs


@pytest.fixture(autouse=True)
def _reset_obs_state(monkeypatch):
    """Each test starts from a clean, otel-off module state."""
    monkeypatch.delenv("MAVERICK_OTEL_EXPORTER", raising=False)
    monkeypatch.delenv("MAVERICK_OTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("MAVERICK_OTEL_HEADERS", raising=False)
    monkeypatch.delenv("MAVERICK_PROMETHEUS_PORT", raising=False)
    monkeypatch.setattr(obs, "_initialized", False, raising=False)
    monkeypatch.setattr(obs, "_tracer", None, raising=False)
    monkeypatch.setattr(obs, "_metrics", {}, raising=False)


# ---------- MAVERICK_OTEL_HEADERS parsing ----------

def test_headers_unset_is_empty(monkeypatch):
    assert obs._otlp_headers() == {}


def test_headers_blank_is_empty(monkeypatch):
    monkeypatch.setenv("MAVERICK_OTEL_HEADERS", "   ")
    assert obs._otlp_headers() == {}


def test_headers_parsed_from_env(monkeypatch):
    monkeypatch.setenv(
        "MAVERICK_OTEL_HEADERS", "x-honeycomb-team=abc123, dd-api-key=xyz"
    )
    assert obs._otlp_headers() == {
        "x-honeycomb-team": "abc123",
        "dd-api-key": "xyz",
    }


def test_headers_skip_malformed_pairs(monkeypatch):
    # A bare token with no '=' is skipped, not crashed on.
    monkeypatch.setenv("MAVERICK_OTEL_HEADERS", "garbage,authorization=Bearer t")
    assert obs._otlp_headers() == {"authorization": "Bearer t"}


# ---------- opt-in / no-op by default ----------

def test_disabled_by_default(monkeypatch):
    assert obs._otel_enabled() is False
    assert obs.is_enabled() is False


def test_trace_span_is_noop_when_disabled(monkeypatch):
    # No tracer is created, span yields None, attributes don't raise.
    with obs.trace_span("chat test-model", attributes={"gen_ai.system": "x"}) as s:
        assert s is None
    assert obs._tracer is None


def test_headers_not_read_when_disabled(monkeypatch):
    # Setting headers without the exporter flag must not enable anything.
    monkeypatch.setenv("MAVERICK_OTEL_HEADERS", "authorization=Bearer t")
    obs._initialize()
    assert obs._tracer is None
    assert obs.is_enabled() is False


# ---------- headers reach the exporter (otel required) ----------

def test_headers_passed_to_exporter_when_enabled(monkeypatch):
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    from opentelemetry.exporter.otlp.proto.http import trace_exporter as te

    captured: dict[str, object] = {}

    class _SpyExporter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def export(self, spans):  # pragma: no cover - never called in test
            return None

        def shutdown(self):  # pragma: no cover
            return None

    monkeypatch.setattr(te, "OTLPSpanExporter", _SpyExporter)
    monkeypatch.setenv("MAVERICK_OTEL_EXPORTER", "otlp")
    monkeypatch.setenv("MAVERICK_OTEL_ENDPOINT", "https://collector.example/v1/traces")
    monkeypatch.setenv("MAVERICK_OTEL_HEADERS", "x-api-key=secret")

    obs._initialize()

    assert captured.get("endpoint") == "https://collector.example/v1/traces"
    assert captured.get("headers") == {"x-api-key": "secret"}
    assert obs._tracer is not None


def test_no_headers_kwarg_omitted_when_unset(monkeypatch):
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    from opentelemetry.exporter.otlp.proto.http import trace_exporter as te

    captured: dict[str, object] = {}

    class _SpyExporter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def export(self, spans):  # pragma: no cover
            return None

        def shutdown(self):  # pragma: no cover
            return None

    monkeypatch.setattr(te, "OTLPSpanExporter", _SpyExporter)
    monkeypatch.setenv("MAVERICK_OTEL_EXPORTER", "otlp")

    obs._initialize()

    # default path: no headers kwarg, so the exporter keeps its own default.
    assert "headers" not in captured


# ---------- tool span gen_ai.* attributes ----------

def test_tool_attributes_minimal():
    a = obs.gen_ai_tool_attributes("read_file")
    assert a["gen_ai.operation.name"] == "execute_tool"
    assert a["gen_ai.tool.name"] == "read_file"
    assert a["gen_ai.tool.type"] == "function"
    # optional fields omitted when unknown
    assert "gen_ai.tool.call.id" not in a
    assert "gen_ai.tool.description" not in a


def test_tool_attributes_full():
    a = obs.gen_ai_tool_attributes(
        "bash", call_id="call_42", description="run a shell command",
        tool_type="function",
    )
    assert a["gen_ai.tool.name"] == "bash"
    assert a["gen_ai.tool.call.id"] == "call_42"
    assert a["gen_ai.tool.description"] == "run a shell command"


def test_tool_helper_exported():
    assert "gen_ai_tool_attributes" in obs.__all__


# ---------- import-safe without otel ----------

def test_module_imports_without_otel(monkeypatch):
    # Re-importing the module must never require opentelemetry at import time.
    mod = importlib.reload(obs)
    assert hasattr(mod, "trace_span")
    assert hasattr(mod, "gen_ai_tool_attributes")
