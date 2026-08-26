"""AkShare 股票能力目录与受控探测。

目录只反射本机已安装的 ``akshare`` 导出；探测必须经目录重新解析目标，
因此不会把调用者给出的名称当作模块路径、表达式或任意可执行对象处理。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from inspect import Parameter
import inspect
import json
import logging
import math
import re
from threading import BoundedSemaphore
import time
from typing import Any

from src.market.infrastructure.akshare_probe_worker import (
    MAX_CONCURRENT_PROBES,
    ProbeCapacityError,
    ProbeWorkerError,
    ProbeWorkerStartError,
    run_akshare_probe,
)
from src.market.infrastructure.akshare_catalog_meta import (
    capability_status,
    category_label,
    execution_mode,
    infer_category,
    infer_source,
    parse_doc_sections,
    source_label,
)
from src.market.infrastructure.akshare_probe_result import (
    JsonValue,
    json_safe,
    summarize_probe_result,
)

from src.market.infrastructure.akshare_catalog_limits import (
    MAX_PROBE_COLLECTION_ITEMS,
    MAX_PROBE_DATE_WINDOW_DAYS,
    MAX_PROBE_JSON_DEPTH,
    MAX_PROBE_JSON_NODES,
    MAX_PROBE_PAGE,
    MAX_PROBE_PARAMS_BYTES,
    MAX_PROBE_SECONDS,
    MAX_PROBE_STRING_LENGTH,
    MAX_SAMPLE_ROWS,
    _annotation_text,
    _apply_probe_defaults,
    _coerce_params,
    _is_json_value,
    _is_page_parameter,
    _probe_sample,
    _validate_and_bind,
    _validate_json_params,
    _validate_probe_limits,
)


CatalogSource = Mapping[str, object] | object | Callable[..., object]

#: MCP 工具调用要的是能算的数据，不是「看一眼」；行数上限比试跑放宽，其余预算不变。
MAX_MCP_SAMPLE_ROWS = 50
_PROBE_SLOTS = BoundedSemaphore(MAX_CONCURRENT_PROBES)
LOGGER = logging.getLogger(__name__)
_SAMPLE_BY_PARAMETER = {
    "symbol": "600519",
    "code": "600519",
    "security": "600519",
    "security_code": "600519",
    "stock": "600519",
    "stock_code": "600519",
    "date": "20250101",
    "trade_date": "20250101",
    "start_date": "20250101",
    "end_date": "20251231",
    "period": "daily",
    "adjust": "",
    "market": "沪深京A股",
    "indicator": "按报告期",
    "year": "2025",
    "quarter": "1",
}


def discover_stock_capabilities(
    resolver: CatalogSource | None = None,
) -> list[dict[str, JsonValue]]:
    """返回本机 AkShare 的真实 ``stock_*`` 可调用导出，按名称稳定排序。

    ``resolver`` 仅为测试或组合根注入模块/映射；默认才导入固定模块名
    ``akshare``，从不根据外部输入动态导入。
    """
    source = _resolve_source(resolver)
    return [
        _capability_entry(name, target)
        for name, target in sorted(_stock_targets(source).items())
    ]


def probe_stock_capability(
    name: str,
    params: Mapping[str, JsonValue] | None = None,
    *,
    resolver: CatalogSource | None = None,
    max_sample_rows: int | None = None,
) -> dict[str, JsonValue]:
    """受控执行一个目录条目并返回小型、JSON 安全的结果摘要。

    参数在执行前以签名校验。函数内的网络、解析等运行期异常会被转换为
    ``error``；目录名、参数名及参数类型错误则直接拒绝给调用方处理。

    ``max_sample_rows`` 只放宽样本行数（上限 ``MAX_MCP_SAMPLE_ROWS``），
    超时、并发、参数校验等预算一律不变。
    """
    if not isinstance(name, str) or not name:
        raise ValueError("capability name must be a non-empty string")
    if params is not None and not isinstance(params, Mapping):
        raise ValueError("params must be an object")

    target = _probe_target(name, resolver)
    if target is None:
        raise ValueError(f"unknown stock capability: {name}")

    incoming = dict(params or {})
    _validate_json_params(incoming)
    signature = _signature(target)
    normalized = _coerce_params(signature, incoming)
    _apply_probe_defaults(signature, normalized)
    _validate_probe_limits(normalized)
    _validate_and_bind(target, signature, normalized)

    sample_rows = _sample_row_budget(max_sample_rows)
    started = time.perf_counter()
    try:
        result = _run_probe_with_budget(
            name, target, normalized, resolver=resolver, max_sample_rows=sample_rows
        )
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        result["error"] = None
        return result
    except (ProbeCapacityError, ProbeWorkerStartError):
        raise
    except ProbeWorkerError as exc:
        LOGGER.warning("AkShare probe failed for %s: %s", name, exc)
        return _failed_probe(started, str(exc))
    except Exception as exc:
        LOGGER.warning("AkShare probe failed for %s: %s", name, exc)
        return _failed_probe(started, f"{type(exc).__name__}: {exc}")


def _failed_probe(started: float, error: str) -> dict[str, JsonValue]:
    """失败结果与成功结果同形，前端不必为报错分支再写一套字段判断。"""
    return {
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "rows": None,
        "columns": [],
        "columns_detail": [],
        "sample": [],
        "truncated": False,
        "error": error,
    }


def _resolve_source(resolver: CatalogSource | None) -> Mapping[str, object]:
    source: object
    if resolver is None:
        import akshare

        source = akshare
    elif callable(resolver) and not isinstance(resolver, Mapping):
        if _is_named_resolver(resolver):
            raise ValueError("named resolver cannot discover a capability catalog")
        source = resolver()
    else:
        source = resolver

    if isinstance(source, Mapping):
        return {str(name): value for name, value in source.items()}
    namespace = vars(source)
    return {str(name): value for name, value in namespace.items()}


def _probe_target(name: str, resolver: CatalogSource | None) -> Callable[..., object] | None:
    if resolver is not None and callable(resolver) and not isinstance(resolver, Mapping):
        if _is_named_resolver(resolver):
            try:
                candidate = resolver(name)
            except KeyError:
                return None
            return _stock_targets({name: candidate}).get(name)
    return _stock_targets(_resolve_source(resolver)).get(name)


def _is_named_resolver(resolver: Callable[..., object]) -> bool:
    try:
        signature = inspect.signature(resolver)
    except (TypeError, ValueError):
        return False
    required_positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.default is Parameter.empty
        and parameter.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(required_positional) == 1


def _stock_targets(source: Mapping[str, object]) -> dict[str, Callable[..., object]]:
    targets: dict[str, Callable[..., object]] = {}
    for name, target in source.items():
        if not name.startswith("stock_") or not callable(target):
            continue
        module = getattr(target, "__module__", "")
        if isinstance(module, str) and module.startswith("akshare."):
            targets[name] = target
    return targets


def _capability_entry(name: str, target: Callable[..., object]) -> dict[str, JsonValue]:
    signature = _signature(target)
    # 样例参数算一遍就够：参数描述里的 sample 与 default_params 本来同源，
    # 各算一次等于每条能力多跑一趟 _sample_params + _apply_safe_date_samples。
    default_params = _sample_params(signature)
    parameters = _parameter_descriptions(signature, default_params)
    raw_doc = inspect.getdoc(target) or ""
    doc = " ".join(raw_doc.split())
    param_docs, returns = parse_doc_sections(raw_doc)
    module = str(getattr(target, "__module__", ""))
    source = infer_source(name, module)
    category = infer_category(name)
    return {
        "name": name,
        "module": module,
        "signature": str(signature),
        "doc": doc[:240],
        "param_docs": param_docs,
        "returns": returns,
        "source": source,
        "source_label": source_label(source),
        "category": category,
        "category_label": category_label(category),
        "default_params": default_params,
        "parameters": parameters,
        "execution_mode": execution_mode(name),
        "status": capability_status(parameters),
    }


def _signature(target: Callable[..., object]) -> inspect.Signature:
    try:
        return inspect.signature(target)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"cannot inspect stock capability signature: {exc}") from exc


def _sample_params(signature: inspect.Signature) -> dict[str, JsonValue]:
    samples: dict[str, JsonValue] = {}
    for parameter in signature.parameters.values():
        if parameter.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
            continue
        if parameter.default is not Parameter.empty:
            if _is_json_value(parameter.default):
                samples[parameter.name] = _probe_sample(parameter.name, parameter.default)
            continue
        sample = _SAMPLE_BY_PARAMETER.get(parameter.name)
        if sample is not None:
            samples[parameter.name] = sample
    _apply_safe_date_samples(signature, samples)
    return samples


def _apply_safe_date_samples(
    signature: inspect.Signature, samples: dict[str, JsonValue]
) -> None:
    """目录样例也必须可直接用于受控试跑，不能暴露上游的全历史默认值。"""
    today = date.today()
    start = today - timedelta(days=MAX_PROBE_DATE_WINDOW_DAYS)
    for parameter_name in ("start_date", "begin_date"):
        if parameter_name in signature.parameters:
            samples[parameter_name] = start.strftime("%Y%m%d")
    if "end_date" in signature.parameters:
        samples["end_date"] = today.strftime("%Y%m%d")


def _parameter_descriptions(
    signature: inspect.Signature, samples: Mapping[str, JsonValue]
) -> list[dict[str, JsonValue]]:
    descriptions: list[dict[str, JsonValue]] = []
    for parameter in signature.parameters.values():
        if parameter.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
            continue
        has_default = parameter.default is not Parameter.empty
        default = (
            json_safe(parameter.default)
            if has_default and _is_json_value(parameter.default)
            else None
        )
        sample = samples.get(parameter.name)
        descriptions.append(
            {
                "name": parameter.name,
                "required": not has_default,
                "kind": parameter.kind.name.lower(),
                "annotation": _annotation_text(parameter.annotation),
                "has_default": has_default,
                "default": default,
                "sample": sample,
            }
        )
    return descriptions


def _sample_row_budget(requested: int | None) -> int:
    if requested is None:
        return MAX_SAMPLE_ROWS
    try:
        rows = int(requested)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_sample_rows must be an integer") from exc
    return max(1, min(rows, MAX_MCP_SAMPLE_ROWS))


def _run_probe_with_budget(
    name: str,
    target: Callable[..., object],
    params: Mapping[str, JsonValue],
    *,
    resolver: CatalogSource | None,
    max_sample_rows: int = MAX_SAMPLE_ROWS,
) -> dict[str, JsonValue]:
    """生产调用在独立进程执行；注入 resolver 只保留给本地测试。"""
    if resolver is None:
        return run_akshare_probe(
            name,
            params,
            timeout_seconds=MAX_PROBE_SECONDS,
            max_sample_rows=max_sample_rows,
            slots=_PROBE_SLOTS,
        )
    # resolver 是测试/组合根注入；生产 HTTP 路径从不传入它，不能遗留不可杀线程。
    value = target(**params)
    return summarize_probe_result(value, max_sample_rows=max_sample_rows)
