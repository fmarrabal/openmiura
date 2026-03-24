from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Tuple


# prometheus_client is optional at development/test time. When unavailable,
# provide a tiny in-process fallback that preserves the public API used by
# openMiura and still emits Prometheus-like text for /metrics.
try:  # pragma: no cover - exercised indirectly when dependency is present
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
    _PROMETHEUS_AVAILABLE = True
except Exception:  # pragma: no cover - fallback path covered by import-time behaviour
    _PROMETHEUS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    class _MetricChild:
        def __init__(self, metric: "_MetricBase", labels: Tuple[str, ...]):
            self.metric = metric
            self.labels_key = tuple(str(x) for x in labels)

        def inc(self, amount: float = 1.0) -> None:
            self.metric.values[self.labels_key] = float(self.metric.values.get(self.labels_key, 0.0)) + float(amount)

        def set(self, value: float) -> None:
            self.metric.values[self.labels_key] = float(value)

        def observe(self, value: float) -> None:
            # For the lightweight fallback we store the sum of observations.
            self.metric.values[self.labels_key] = float(self.metric.values.get(self.labels_key, 0.0)) + float(value)

    class _MetricBase:
        def __init__(self, name: str, documentation: str, labelnames=()):
            self.name = str(name)
            self.documentation = str(documentation)
            self.labelnames = tuple(labelnames or ())
            self.values: Dict[Tuple[str, ...], float] = {}
            _REGISTRY.append(self)

        def labels(self, **kwargs):
            key = tuple(str(kwargs.get(label, "")) for label in self.labelnames)
            return _MetricChild(self, key)

        def inc(self, amount: float = 1.0) -> None:
            self.values[()] = float(self.values.get((), 0.0)) + float(amount)

        def set(self, value: float) -> None:
            self.values[()] = float(value)

        def observe(self, value: float) -> None:
            self.values[()] = float(self.values.get((), 0.0)) + float(value)

    class Counter(_MetricBase):
        pass

    class Gauge(_MetricBase):
        pass

    class Histogram(_MetricBase):
        pass

    _REGISTRY: list[_MetricBase] = []

    def generate_latest() -> bytes:
        lines: list[str] = []
        for metric in _REGISTRY:
            lines.append(f"# HELP {metric.name} {metric.documentation}")
            lines.append(f"# TYPE {metric.name} gauge")
            if not metric.values:
                lines.append(f"{metric.name} 0")
                continue
            for label_values, value in metric.values.items():
                if metric.labelnames:
                    rendered = ",".join(
                        f'{name}="{val}"' for name, val in zip(metric.labelnames, label_values)
                    )
                    lines.append(f"{metric.name}{{{rendered}}} {value}")
                else:
                    lines.append(f"{metric.name} {value}")
        return ("\n".join(lines) + "\n").encode("utf-8")


REQUESTS_TOTAL = Counter(
    "openmiura_requests_total",
    "Total inbound requests processed by openMiura.",
    labelnames=("channel", "status"),
)
LATENCY_SECONDS = Histogram(
    "openmiura_latency_seconds",
    "End-to-end request latency in seconds.",
    labelnames=("channel",),
)
MEMORY_ITEMS_TOTAL = Gauge(
    "openmiura_memory_items_total",
    "Current number of memory items by kind.",
    labelnames=("kind",),
)
TOKENS_USED_TOTAL = Counter(
    "openmiura_tokens_used_total",
    "Total tokens reported by the LLM backend.",
    labelnames=("model",),
)
ACTIVE_SESSIONS = Gauge(
    "openmiura_active_sessions",
    "Active sessions over the last 24h.",
)
TOOL_CALLS_TOTAL = Counter(
    "openmiura_tool_calls_total",
    "Tool calls by tool name and status.",
    labelnames=("tool", "status"),
)
ERRORS_TOTAL = Counter(
    "openmiura_errors_total",
    "Total errors observed by type.",
    labelnames=("type",),
)


@contextmanager
def observe_request(channel: str):
    t0 = time.perf_counter()
    status = "ok"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        LATENCY_SECONDS.labels(channel=str(channel or "unknown")).observe(max(0.0, time.perf_counter() - t0))
        REQUESTS_TOTAL.labels(channel=str(channel or "unknown"), status=status).inc()


def record_error(error_type: str) -> None:
    ERRORS_TOTAL.labels(type=str(error_type or "unknown")).inc()


def record_tool_call(tool_name: str, ok: bool) -> None:
    TOOL_CALLS_TOTAL.labels(tool=str(tool_name or "unknown"), status="ok" if ok else "error").inc()


def record_tokens(model: str, prompt_tokens: int | None = None, completion_tokens: int | None = None, total_tokens: int | None = None) -> None:
    total = int(total_tokens or 0)
    if total <= 0:
        total = int(prompt_tokens or 0) + int(completion_tokens or 0)
    if total > 0:
        TOKENS_USED_TOTAL.labels(model=str(model or "unknown")).inc(total)


def update_memory_metrics(audit) -> None:
    counts = getattr(audit, "count_memory_items_by_kind", lambda: {})() or {}
    seen = set()
    for kind, total in counts.items():
        MEMORY_ITEMS_TOTAL.labels(kind=str(kind)).set(int(total))
        seen.add(str(kind))
    for kind in ("fact", "preference", "user_note", "tool_result"):
        if kind not in seen:
            MEMORY_ITEMS_TOTAL.labels(kind=kind).set(0)
    ACTIVE_SESSIONS.set(int(getattr(audit, "count_active_sessions", lambda **_: 0)(window_s=86400)))


def metrics_payload(audit=None) -> tuple[bytes, str]:
    if audit is not None:
        try:
            update_memory_metrics(audit)
        except Exception:
            record_error("metrics_snapshot")
    return generate_latest(), CONTENT_TYPE_LATEST
