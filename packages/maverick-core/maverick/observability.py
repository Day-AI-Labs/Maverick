"""Opt-in OpenTelemetry + Prometheus exporters.

Off by default. Three knobs:

  - ``MAVERICK_OTEL_EXPORTER=otlp``      enables OTLP span export
  - ``MAVERICK_OTEL_ENDPOINT=https://...``  override default collector URL
  - ``MAVERICK_OTEL_HEADERS=k1=v1,k2=v2`` per-request headers on the OTLP
    exporter (e.g. ``x-honeycomb-team=...`` / ``dd-api-key=...`` so traces
    reach a managed backend like Honeycomb / Datadog / Grafana Cloud)
  - ``MAVERICK_PROMETHEUS_PORT=9100``    expose /metrics on this port
  - ``MAVERICK_PROMETHEUS_ADDR=127.0.0.1`` bind address for /metrics

When neither is set, this module is a pure-Python no-op: ``trace_span()``
returns a context-manager that does nothing, ``record_metric()`` is a
no-op.

When enabled, it wraps:
  - Agent kernel turns (one span per LLM call)
  - Tool invocations (one span per tool call, attributes = tool name +
    result-size + ms)
  - Provider dispatches (provider + model + tokens + cost in attributes)

Deps are heavyweight + optional. Install with:
    pip install 'maverick-agent[observability]'

Failures during span/metric export are logged and swallowed.
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
from collections.abc import Iterator
from typing import Any

log = logging.getLogger(__name__)


_initialized = False
_init_lock = threading.Lock()
_tracer: Any = None
_sentry: Any = None
_metrics: dict[str, Any] = {}


def _otel_enabled() -> bool:
    return bool(os.environ.get("MAVERICK_OTEL_EXPORTER"))


def _sentry_dsn() -> str:
    """Sentry DSN from env or [observability] sentry_dsn (empty = off)."""
    dsn = os.environ.get("MAVERICK_SENTRY_DSN", "").strip()
    if dsn:
        return dsn
    try:
        from .config import load_config
        return str((load_config() or {}).get("observability", {}).get("sentry_dsn") or "").strip()
    except Exception:  # pragma: no cover -- config never blocks init
        return ""


def _sentry_enabled() -> bool:
    return bool(_sentry_dsn())


def _prometheus_enabled() -> bool:
    return bool(os.environ.get("MAVERICK_PROMETHEUS_PORT"))


def _otlp_headers() -> dict[str, str]:
    """Parse ``MAVERICK_OTEL_HEADERS`` into a header dict for the exporter.

    Format mirrors the OTel-standard ``OTEL_EXPORTER_OTLP_HEADERS``:
    comma-separated ``key=value`` pairs (``x-honeycomb-team=abc,dd-api-key=xyz``).
    Returns ``{}`` when unset/blank so the default (no headers) is unchanged.
    Malformed pairs (no ``=``) are skipped rather than crashing init.
    """
    raw = os.environ.get("MAVERICK_OTEL_HEADERS", "").strip()
    if not raw:
        return {}
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        key, sep, value = pair.partition("=")
        key = key.strip()
        if sep and key:
            headers[key] = value.strip()
    return headers


def _initialize() -> None:
    """Idempotent setup. Imports happen here so the module is cheap to
    import when observability is off."""
    global _initialized, _tracer, _sentry
    with _init_lock:
        if _initialized:
            return
        _initialized = True

        if _sentry_enabled():
            # Sentry performance tab: init with tracing on so trace_span()
            # also opens Sentry spans (transactions at the root). Sample rate
            # via MAVERICK_SENTRY_TRACES_SAMPLE_RATE (default 0.1).
            try:
                import sentry_sdk
                try:
                    rate = float(os.environ.get("MAVERICK_SENTRY_TRACES_SAMPLE_RATE", "0.1"))
                except ValueError:
                    rate = 0.1
                sentry_sdk.init(
                    dsn=_sentry_dsn(),
                    traces_sample_rate=max(0.0, min(1.0, rate)),
                    # The runtime handles prompts/results; never attach local
                    # variables or request bodies to events.
                    include_local_variables=False,
                    send_default_pii=False,
                )
                _sentry = sentry_sdk
                log.info("observability: Sentry performance tracing on")
            except ImportError:
                log.warning(
                    "observability: MAVERICK_SENTRY_DSN set but sentry-sdk is "
                    "not installed. pip install 'maverick-agent[sentry]'")

        if _otel_enabled():
            try:
                from opentelemetry import trace
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )
                from opentelemetry.sdk.resources import Resource
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import BatchSpanProcessor
            except ImportError:
                log.warning(
                    "observability: opentelemetry not installed. "
                    "Install with: pip install 'maverick-agent[observability]'"
                )
                return
            endpoint = os.environ.get(
                "MAVERICK_OTEL_ENDPOINT", "http://localhost:4318/v1/traces"
            )
            headers = _otlp_headers()
            resource = Resource.create({"service.name": "maverick"})
            provider = TracerProvider(resource=resource)
            try:
                # Pass headers only when set so the no-header default path is
                # byte-for-byte unchanged for collectors that don't need auth.
                exporter = (
                    OTLPSpanExporter(endpoint=endpoint, headers=headers)
                    if headers
                    else OTLPSpanExporter(endpoint=endpoint)
                )
                provider.add_span_processor(BatchSpanProcessor(exporter))
            except Exception as e:
                log.warning("observability: OTLP exporter init failed: %s", e)
                return
            trace.set_tracer_provider(provider)
            _tracer = trace.get_tracer("maverick")
            log.info(
                "observability: OTLP traces -> %s (%d header(s))",
                endpoint, len(headers),
            )

        if _prometheus_enabled():
            try:
                from prometheus_client import Counter, Histogram, start_http_server
            except ImportError:
                log.warning(
                    "observability: prometheus_client not installed. "
                    "Install with: pip install 'maverick-agent[observability]'"
                )
                return
            port_str = os.environ.get("MAVERICK_PROMETHEUS_PORT", "9100")
            addr = os.environ.get("MAVERICK_PROMETHEUS_ADDR", "127.0.0.1")
            try:
                port = int(port_str)
                start_http_server(port, addr=addr)
            except (OSError, ValueError) as e:
                log.warning("observability: Prometheus exporter failed: %s", e)
                return
            _metrics["llm_calls"] = Counter(
                "maverick_llm_calls_total",
                "Total LLM API calls", ["provider", "model"],
            )
            _metrics["llm_latency"] = Histogram(
                "maverick_llm_latency_seconds",
                "LLM call latency", ["provider", "model"],
            )
            _metrics["llm_tokens"] = Counter(
                "maverick_llm_tokens_total",
                "Total tokens billed", ["provider", "model", "direction"],
            )
            # Prompt-cache effectiveness: input tokens served from cache
            # (~0.1x cost), written to cache (~1.25-2x), and processed fresh
            # (full price). Hit rate = cache_read / (cache_read + input). A
            # value stuck near zero across a run flags a silent cache
            # invalidator (a date/UUID in the system prompt, an unstable tool
            # order) -- the cheapest regression to catch and the dearest to miss.
            _metrics["llm_cache_tokens"] = Counter(
                "maverick_llm_cache_tokens_total",
                "Prompt-cache input tokens", ["provider", "model", "kind"],
            )
            _metrics["tool_calls"] = Counter(
                "maverick_tool_calls_total",
                "Tool invocations", ["tool", "status"],
            )
            # Lifetime total -> a Counter (monotonic, accumulates via inc()).
            # It used to be a Gauge fed `.set(budget.dollars)` from the per-goal
            # Budget accumulator, so a second goal starting fresh at $0 stomped
            # the running total back down. Callers now inc() by each call's
            # delta, which sums to a true cross-goal lifetime spend.
            _metrics["budget_dollars"] = Counter(
                "maverick_budget_dollars_spent",
                "Total dollars spent (lifetime)",
            )
            log.info("observability: Prometheus /metrics on %s:%d", addr, port)


@contextlib.contextmanager
def trace_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Context manager that opens a span (no-op when off).

    With Sentry configured, the same call also opens a Sentry span — a
    transaction when there is no active one (episodes), a child span inside
    one (tools) — so the existing instrumentation points feed Sentry's
    performance tab with zero new call sites.
    """
    _initialize()
    with contextlib.ExitStack() as stack:
        if _sentry is not None:
            try:
                if _sentry.get_current_scope().transaction is None:
                    sspan = stack.enter_context(
                        _sentry.start_transaction(name=name, op="maverick"))
                else:
                    sspan = stack.enter_context(_sentry.start_span(op=name))
                for k, v in (attributes or {}).items():
                    try:
                        sspan.set_data(k, v)
                    except Exception:
                        pass
            except Exception:  # pragma: no cover -- sentry must never break a run
                pass
        if _tracer is None:
            yield None
            return
        with _tracer.start_as_current_span(name) as span:
            if attributes:
                for k, v in attributes.items():
                    try:
                        span.set_attribute(k, v)
                    except Exception:
                        pass
            yield span


def record_metric(
    name: str,
    value: float = 1.0,
    *,
    labels: dict[str, str] | None = None,
) -> None:
    """Bump a known counter / observe a histogram / set a gauge."""
    _initialize()
    metric = _metrics.get(name)
    if metric is None:
        return
    labels = labels or {}
    try:
        # Resolve the label child once. Calling metric.labels() with the
        # wrong (or empty) label set raises in prometheus_client, so only
        # scope when labels are actually provided.
        scoped = metric.labels(**labels) if labels else metric
        # Histograms expose observe(); gauges expose set() *and* inc();
        # counters expose inc(). Prefer set() before inc() so gauges are
        # updated as absolute values rather than accumulated.
        if hasattr(scoped, "observe"):
            scoped.observe(value)
        elif hasattr(scoped, "set"):
            scoped.set(value)
        elif hasattr(scoped, "inc"):
            scoped.inc(value)
    except Exception:  # pragma: no cover -- never crash on metric export
        log.debug("metric %s failed", name, exc_info=True)


def is_enabled() -> bool:
    """True if either OTEL or Prometheus is configured."""
    return _otel_enabled() or _prometheus_enabled() or _sentry_enabled()


# --- OpenTelemetry GenAI semantic conventions (gen_ai.*) -------------------
# These attribute names are the cross-vendor standard for LLM/agent
# telemetry (OTel semconv). Emitting them means traces Maverick produces are
# legible to any OTel-aware backend (Grafana, Honeycomb, Arize Phoenix, ...)
# without custom attribute mapping -- the convention that became the
# observability standard for agents in 2026.

def gen_ai_span_name(operation: str, model: str) -> str:
    """OTel GenAI convention: a span is named ``"<operation> <model>"``."""
    return f"{operation} {model}"


def gen_ai_attributes(
    system: str,
    request_model: str,
    *,
    operation: str = "chat",
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
    response_model: str | None = None,
    response_id: str | None = None,
    finish_reasons: list[str] | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> dict[str, Any]:
    """Build an OTel GenAI-semconv attribute dict for an LLM span.

    ``system`` is the provider slug (anthropic/openai/gemini/...). Covers the
    full GenAI request + response attribute set; only the fields that are known
    are included, so request-time and response-time attributes can be built in
    two passes (the response side filled once the call returns).
    """
    attrs: dict[str, Any] = {
        "gen_ai.operation.name": operation,
        "gen_ai.system": system,
        "gen_ai.request.model": request_model,
    }
    # -- request parameters (gen_ai.request.*) --
    if max_tokens is not None:
        attrs["gen_ai.request.max_tokens"] = max_tokens
    if temperature is not None:
        attrs["gen_ai.request.temperature"] = temperature
    if top_p is not None:
        attrs["gen_ai.request.top_p"] = top_p
    if frequency_penalty is not None:
        attrs["gen_ai.request.frequency_penalty"] = frequency_penalty
    if presence_penalty is not None:
        attrs["gen_ai.request.presence_penalty"] = presence_penalty
    # -- response (gen_ai.response.*) --
    if response_model is not None:
        attrs["gen_ai.response.model"] = response_model
    if response_id is not None:
        attrs["gen_ai.response.id"] = response_id
    if finish_reasons is not None:
        attrs["gen_ai.response.finish_reasons"] = list(finish_reasons)
    # -- usage (gen_ai.usage.*) --
    if input_tokens is not None:
        attrs["gen_ai.usage.input_tokens"] = input_tokens
    if output_tokens is not None:
        attrs["gen_ai.usage.output_tokens"] = output_tokens
    return attrs


def gen_ai_tool_attributes(
    tool_name: str,
    *,
    call_id: str | None = None,
    description: str | None = None,
    tool_type: str = "function",
) -> dict[str, Any]:
    """Build an OTel GenAI-semconv attribute dict for a tool-execution span.

    The convention models a tool call as the ``execute_tool`` operation with
    ``gen_ai.tool.name`` / ``gen_ai.tool.call.id`` / ``gen_ai.tool.type``, the
    counterpart to :func:`gen_ai_attributes` for LLM spans. Optional fields are
    omitted when unknown so a caller that only knows the tool name still emits a
    valid span.
    """
    attrs: dict[str, Any] = {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": tool_name,
        "gen_ai.tool.type": tool_type,
    }
    if call_id is not None:
        attrs["gen_ai.tool.call.id"] = call_id
    if description is not None:
        attrs["gen_ai.tool.description"] = description
    return attrs


__all__ = [
    "trace_span", "record_metric", "is_enabled",
    "gen_ai_span_name", "gen_ai_attributes", "gen_ai_tool_attributes",
]
