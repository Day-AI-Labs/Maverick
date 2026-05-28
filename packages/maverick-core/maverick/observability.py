"""Opt-in OpenTelemetry + Prometheus exporters.

Off by default. Three knobs:

  - ``MAVERICK_OTEL_EXPORTER=otlp``      enables OTLP span export
  - ``MAVERICK_OTEL_ENDPOINT=https://...``  override default collector URL
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
from typing import Any, Iterator, Optional

log = logging.getLogger(__name__)


_initialized = False
_init_lock = threading.Lock()
_tracer: Any = None
_metrics: dict[str, Any] = {}


def _otel_enabled() -> bool:
    return bool(os.environ.get("MAVERICK_OTEL_EXPORTER"))


def _prometheus_enabled() -> bool:
    return bool(os.environ.get("MAVERICK_PROMETHEUS_PORT"))


def _initialize() -> None:
    """Idempotent setup. Imports happen here so the module is cheap to
    import when observability is off."""
    global _initialized, _tracer
    with _init_lock:
        if _initialized:
            return
        _initialized = True

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
            resource = Resource.create({"service.name": "maverick"})
            provider = TracerProvider(resource=resource)
            try:
                exporter = OTLPSpanExporter(endpoint=endpoint)
                provider.add_span_processor(BatchSpanProcessor(exporter))
            except Exception as e:
                log.warning("observability: OTLP exporter init failed: %s", e)
                return
            trace.set_tracer_provider(provider)
            _tracer = trace.get_tracer("maverick")
            log.info("observability: OTLP traces -> %s", endpoint)

        if _prometheus_enabled():
            try:
                from prometheus_client import Counter, Gauge, Histogram, start_http_server
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
            _metrics["tool_calls"] = Counter(
                "maverick_tool_calls_total",
                "Tool invocations", ["tool", "status"],
            )
            _metrics["budget_dollars"] = Gauge(
                "maverick_budget_dollars_spent",
                "Total dollars spent (lifetime)",
            )
            log.info("observability: Prometheus /metrics on %s:%d", addr, port)


@contextlib.contextmanager
def trace_span(
    name: str,
    *,
    attributes: Optional[dict[str, Any]] = None,
) -> Iterator[Any]:
    """Context manager that opens a span (no-op when off)."""
    _initialize()
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
    labels: Optional[dict[str, str]] = None,
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
    return _otel_enabled() or _prometheus_enabled()


__all__ = ["trace_span", "record_metric", "is_enabled"]
