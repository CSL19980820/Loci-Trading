"""本地优先的低基数可观测性与相关性上下文。

默认只在进程内保存相关性字段，不配置 exporter，也不向外发送数据。
``LOCI_OBSERVABILITY=1`` 才会发结构化日志和内存 metrics；若额外设置
``LOCI_OBSERVABILITY_OTEL=1``，且环境已安装 OpenTelemetry API/SDK，才会
创建 span。这个模块刻意不安装或配置 exporter，桌面离线行为保持不变。
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
import json
import logging
import os
import re
from threading import Lock
from time import perf_counter
from types import MappingProxyType
from typing import Any
from uuid import uuid4

_CORRELATION_KEYS = (
    "trace_id",
    "run_id",
    "job_id",
    "source_id",
    "tool_receipt_id",
)
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LOW_CARDINALITY_LABELS = {
    "component",
    "operation",
    "status",
    "kind",
    "lane",
    "protocol",
    "outcome",
    "reason",
}
#: **默认值必须不可变。** ContextVar 的 default 是所有上下文共享的**同一个对象**，
#: 给一个真 dict 意味着任何一处原地写入（`current_values()[k] = v`）都会永久污染
#: 每一个还没显式 set 过的上下文——多租户下就是 A 的 trace_id 漏进 B 的日志，而且
#: 不报错、不可复现。只读映射让这种写法当场 TypeError。
_CURRENT: ContextVar[Mapping[str, str]] = ContextVar(
    "loci_observability_correlation",
    default=MappingProxyType({}),
)
_METRICS: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()
_METRIC_LOCK = Lock()


@dataclass(frozen=True)
class Correlation:
    """当前调用链可安全放入日志的相关性字段。"""

    trace_id: str = ""
    run_id: str = ""
    job_id: str = ""
    source_id: str = ""
    tool_receipt_id: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            key: value
            for key, value in (
                ("trace_id", self.trace_id),
                ("run_id", self.run_id),
                ("job_id", self.job_id),
                ("source_id", self.source_id),
                ("tool_receipt_id", self.tool_receipt_id),
            )
            if value
        }


def enabled() -> bool:
    """结构化本地观测是否显式开启。"""
    return _env_flag("LOCI_OBSERVABILITY")


def otel_enabled() -> bool:
    """是否显式允许接入已由宿主配置的 OpenTelemetry tracer。"""
    return enabled() and _env_flag("LOCI_OBSERVABILITY_OTEL")


def new_id(prefix: str) -> str:
    """生成不含业务数据的相关性 ID。"""
    safe_prefix = re.sub(r"[^A-Za-z0-9_-]", "-", str(prefix or "id")).strip("-_") or "id"
    return f"{safe_prefix}-{uuid4().hex[:16]}"


def current() -> Correlation:
    """读取当前 contextvars 相关性快照。"""
    values = _CURRENT.get()
    return Correlation(**{key: str(values.get(key) or "") for key in _CORRELATION_KEYS})


def current_dict() -> dict[str, str]:
    """返回可序列化的当前相关性字段副本。"""
    return current().as_dict()


def valid_id(value: Any) -> str:
    """只接受短、无空白的相关性值，拒绝把用户正文写入日志。"""
    text = str(value or "").strip()
    return text if _ID_PATTERN.fullmatch(text) else ""


def header_values(headers: Mapping[str, str]) -> dict[str, str]:
    """读取受限的内部相关性头；不合法值被忽略。"""
    names = {
        "trace_id": "x-loci-trace-id",
        "run_id": "x-loci-run-id",
        "job_id": "x-loci-job-id",
        "source_id": "x-loci-source-id",
        "tool_receipt_id": "x-loci-tool-receipt-id",
    }
    return {
        key: value
        for key, header in names.items()
        if (value := valid_id(headers.get(header, "")))
    }


@contextmanager
def correlation_scope(
    *,
    trace_id: str | None = None,
    run_id: str | None = None,
    job_id: str | None = None,
    source_id: str | None = None,
    tool_receipt_id: str | None = None,
) -> Iterator[Correlation]:
    """在当前 async/thread 上暂时覆盖相关性字段。"""
    previous = _CURRENT.get()
    values = dict(previous)
    supplied = {
        "trace_id": trace_id,
        "run_id": run_id,
        "job_id": job_id,
        "source_id": source_id,
        "tool_receipt_id": tool_receipt_id,
    }
    for key, raw in supplied.items():
        if raw is not None:
            value = valid_id(raw)
            if value:
                values[key] = value
            else:
                values.pop(key, None)
    token = _CURRENT.set(values)
    try:
        yield current()
    finally:
        _CURRENT.reset(token)


def _metric_labels(labels: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    """只保留预先枚举的低基数标签；相关性 ID 永不进入 metrics。"""
    if not labels:
        return ()
    result: list[tuple[str, str]] = []
    for key, raw in labels.items():
        name = str(key)
        if name not in _LOW_CARDINALITY_LABELS:
            continue
        value = str(raw or "unknown").strip()[:48] or "unknown"
        result.append((name, value))
    return tuple(sorted(result))


def metric(
    name: str,
    *,
    value: int | float = 1,
    labels: Mapping[str, Any] | None = None,
) -> None:
    """记录本地内存 counter；不写库、不发网络。"""
    if not enabled():
        return
    key = (str(name)[:120], _metric_labels(labels))
    with _METRIC_LOCK:
        _METRICS[key] += value


def metrics_snapshot() -> list[dict[str, Any]]:
    """导出测试/本地诊断用快照，不包含相关性 ID。"""
    with _METRIC_LOCK:
        rows = [
            {"name": name, "labels": dict(labels), "value": value}
            for (name, labels), value in sorted(_METRICS.items())
        ]
    return rows


def reset_metrics() -> None:
    """清空进程内 metrics，供测试和本地诊断使用。"""
    with _METRIC_LOCK:
        _METRICS.clear()


def record_lock_wait(
    *,
    component: str,
    kind: str,
    wait_ms: int,
    outcome: str,
    reason: str = "",
) -> None:
    """记录行情/Job 锁等待（低基数）；默认关闭时无副作用。"""
    labels: dict[str, str] = {
        "component": str(component or "unknown")[:48],
        "kind": str(kind or "unknown")[:48],
        "operation": "lock_wait",
        "outcome": str(outcome or "unknown")[:48],
    }
    if reason:
        labels["reason"] = str(reason)[:48]
    metric("loci.lock.wait_ms", value=max(0, int(wait_ms)), labels=labels)
    metric("loci.lock.acquire", labels=labels)


def event(
    logger: logging.Logger,
    level: int,
    name: str,
    *,
    fields: Mapping[str, Any] | None = None,
) -> None:
    """输出一行 JSON 结构化日志；默认不输出。"""
    if not enabled():
        return
    payload: dict[str, Any] = {"event": str(name)[:120], **current_dict()}
    if fields:
        # 调用方负责只传低敏、低基数业务字段；字符串再做长度保护。
        for key, value in fields.items():
            if key in _CORRELATION_KEYS:
                continue
            payload[str(key)[:64]] = value[:256] if isinstance(value, str) else value
    logger.log(level, "loci_observation %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))


@contextmanager
def span(
    name: str,
    *,
    trace_id: str | None = None,
    run_id: str | None = None,
    job_id: str | None = None,
    source_id: str | None = None,
    tool_receipt_id: str | None = None,
    labels: Mapping[str, Any] | None = None,
) -> Iterator[Correlation]:
    """创建本地相关性 span，并可选桥接宿主已配置的 OTel tracer。"""
    inherited = current()
    resolved_trace = valid_id(trace_id) or inherited.trace_id or new_id("trace")
    otel = _otel_span(name) if otel_enabled() else nullcontext(None)
    started = perf_counter()
    with otel as otel_span:
        otel_trace = _otel_trace_id(otel_span)
        with correlation_scope(
            trace_id=otel_trace or resolved_trace,
            run_id=run_id,
            job_id=job_id,
            source_id=source_id,
            tool_receipt_id=tool_receipt_id,
        ) as correlation:
            _set_otel_attributes(otel_span, labels)
            outcome = "ok"
            try:
                yield correlation
            except Exception as exc:
                outcome = "error"
                _set_otel_status(otel_span, error=str(exc))
                metric("loci.span.errors", labels={**(labels or {}), "outcome": "error"})
                raise
            finally:
                metric(
                    "loci.span.duration_ms",
                    value=max(0, int((perf_counter() - started) * 1000)),
                    labels={**(labels or {}), "outcome": outcome},
                )


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _otel_span(name: str) -> Any:
    try:
        from opentelemetry import trace
    except ImportError:
        return nullcontext(None)
    return trace.get_tracer("loci").start_as_current_span(str(name)[:120])


def _otel_trace_id(otel_span: Any) -> str:
    if otel_span is None:
        return ""
    try:
        context = otel_span.get_span_context()
        if context.is_valid:
            return f"trace-{context.trace_id:032x}"
    except (AttributeError, TypeError, ValueError):
        return ""
    return ""


def _set_otel_attributes(otel_span: Any, labels: Mapping[str, Any] | None) -> None:
    if otel_span is None or not labels:
        return
    try:
        for key, value in _metric_labels(labels):
            otel_span.set_attribute(f"loci.{key}", value)
    except (AttributeError, TypeError, ValueError):
        return


def _set_otel_status(otel_span: Any, *, error: str) -> None:
    if otel_span is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        otel_span.set_status(Status(StatusCode.ERROR, str(error)[:256]))
    except (ImportError, AttributeError, TypeError, ValueError):
        return


__all__ = [
    "Correlation",
    "correlation_scope",
    "current",
    "current_dict",
    "enabled",
    "event",
    "header_values",
    "metric",
    "metrics_snapshot",
    "new_id",
    "otel_enabled",
    "record_lock_wait",
    "reset_metrics",
    "span",
    "valid_id",
]
