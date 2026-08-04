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


CatalogSource = Mapping[str, object] | object | Callable[..., object]

MAX_SAMPLE_ROWS = 5
#: MCP 工具调用要的是能算的数据，不是「看一眼」；行数上限比试跑放宽，其余预算不变。
MAX_MCP_SAMPLE_ROWS = 50
MAX_PROBE_PAGE = 5
MAX_PROBE_STRING_LENGTH = 128
MAX_PROBE_COLLECTION_ITEMS = 20
MAX_PROBE_DATE_WINDOW_DAYS = 31
MAX_PROBE_SECONDS = 8.0
MAX_PROBE_JSON_DEPTH = 4
MAX_PROBE_JSON_NODES = 128
MAX_PROBE_PARAMS_BYTES = 16 * 1024
_PROBE_SLOTS = BoundedSemaphore(MAX_CONCURRENT_PROBES)
_PROBE_DATE_PARAMETERS = frozenset(
    {"date", "trade_date", "start_date", "begin_date", "end_date"}
)
_PROBE_ROW_LIMIT_PARAMETERS = frozenset({"limit", "size", "count", "num", "top"})
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
    parameters = _parameter_descriptions(signature)
    default_params = _sample_params(signature)
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


def _parameter_descriptions(signature: inspect.Signature) -> list[dict[str, JsonValue]]:
    descriptions: list[dict[str, JsonValue]] = []
    samples = _sample_params(signature)
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


def _probe_sample(name: str, value: object) -> JsonValue:
    """保留上游默认值，同时给可能大批量的分页接口一个小样本。"""
    if _is_page_parameter(name) and isinstance(value, int) and not isinstance(value, bool):
        return min(max(value, 1), MAX_PROBE_PAGE)
    return json_safe(value)


def _annotation_text(annotation: object) -> str | None:
    if annotation is Parameter.empty:
        return None
    if isinstance(annotation, str):
        return annotation
    return inspect.formatannotation(annotation)


def _validate_json_params(params: Mapping[str, object]) -> None:
    if len(params) > MAX_PROBE_COLLECTION_ITEMS:
        raise ValueError(f"at most {MAX_PROBE_COLLECTION_ITEMS} probe parameters are allowed")
    pending: list[tuple[object, int]] = []
    seen_containers: set[int] = set()
    for key, value in params.items():
        if not isinstance(key, str):
            raise ValueError("parameter names must be strings")
        if len(key) > MAX_PROBE_STRING_LENGTH:
            raise ValueError("parameter names exceed the maximum length")
        pending.append((value, 1))

    node_count = 0
    while pending:
        value, depth = pending.pop()
        node_count += 1
        if node_count > MAX_PROBE_JSON_NODES:
            raise ValueError("probe JSON contains too many values")
        if depth > MAX_PROBE_JSON_DEPTH:
            raise ValueError("probe JSON nesting exceeds the maximum depth")
        if value is None or isinstance(value, (bool, str, int)):
            continue
        if isinstance(value, float):
            if math.isfinite(value):
                continue
            raise ValueError("probe JSON numbers must be finite")
        if isinstance(value, list):
            if id(value) in seen_containers:
                raise ValueError("probe JSON must not contain repeated containers")
            if len(value) > MAX_PROBE_COLLECTION_ITEMS:
                raise ValueError("probe JSON arrays contain too many values")
            seen_containers.add(id(value))
            pending.extend((item, depth + 1) for item in value)
            continue
        if isinstance(value, dict):
            if id(value) in seen_containers:
                raise ValueError("probe JSON must not contain repeated containers")
            if len(value) > MAX_PROBE_COLLECTION_ITEMS:
                raise ValueError("probe JSON objects contain too many fields")
            seen_containers.add(id(value))
            for key, item in value.items():
                if not isinstance(key, str) or len(key) > MAX_PROBE_STRING_LENGTH:
                    raise ValueError("probe JSON object field names are invalid")
                pending.append((item, depth + 1))
            continue
        raise ValueError("probe parameters must contain JSON primitive values only")

    encoded = json.dumps(params, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_PROBE_PARAMS_BYTES:
        raise ValueError("probe JSON exceeds the maximum serialized size")


def _coerce_params(
    signature: inspect.Signature, params: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    """按公开签名的基础标注归一 JSON 值，避免字符串页码传给上游。"""
    normalized: dict[str, JsonValue] = {}
    for name, value in params.items():
        parameter = signature.parameters.get(name)
        normalized[name] = value if parameter is None else _coerce_value(name, value, parameter.annotation)
    return normalized


def _coerce_value(name: str, value: JsonValue, annotation: object) -> JsonValue:
    kind = _annotation_kind(annotation)
    if kind == "int":
        return _coerce_int(name, value)
    if kind == "float":
        return _coerce_float(name, value)
    if kind == "bool":
        return _coerce_bool(name, value)
    return value


def _annotation_kind(annotation: object) -> str | None:
    text = (_annotation_text(annotation) or "").casefold()
    if re.search(r"(?<![a-z_])bool(?:ean)?(?![a-z_])", text):
        return "bool"
    if re.search(r"(?<![a-z_])int(?:eger)?(?![a-z_])", text):
        return "int"
    if re.search(r"(?<![a-z_])(?:float|decimal|number)(?![a-z_])", text):
        return "float"
    return None


def _coerce_int(name: str, value: JsonValue) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            raise ValueError(f"parameter {name!r} must be an integer") from exc
    raise ValueError(f"parameter {name!r} must be an integer")


def _coerce_float(name: str, value: JsonValue) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError as exc:
            raise ValueError(f"parameter {name!r} must be a number") from exc
    else:
        raise ValueError(f"parameter {name!r} must be a number")
    if not math.isfinite(number):
        raise ValueError(f"parameter {name!r} must be a finite number")
    return number


def _coerce_bool(name: str, value: JsonValue) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise ValueError(f"parameter {name!r} must be a boolean")


def _apply_probe_defaults(
    signature: inspect.Signature, params: dict[str, JsonValue]
) -> None:
    """覆盖上游的大范围默认值，未提交的日期也必须保持在探测窗口内。"""
    for parameter in signature.parameters.values():
        if parameter.name in params or parameter.default is Parameter.empty:
            continue
        if _is_page_parameter(parameter.name):
            sample = _probe_sample(parameter.name, parameter.default)
            if isinstance(sample, int) and not isinstance(sample, bool):
                params[parameter.name] = sample
        elif _is_row_limit_parameter(parameter.name):
            if isinstance(parameter.default, int) and not isinstance(parameter.default, bool):
                params[parameter.name] = min(max(parameter.default, 1), MAX_SAMPLE_ROWS)

    today = date.today()
    start = today - timedelta(days=MAX_PROBE_DATE_WINDOW_DAYS)
    for parameter_name in ("start_date", "begin_date"):
        if parameter_name in signature.parameters and parameter_name not in params:
            params[parameter_name] = start.strftime("%Y%m%d")
    if "end_date" in signature.parameters and "end_date" not in params:
        params["end_date"] = today.strftime("%Y%m%d")
    if "timeout" in signature.parameters and "timeout" not in params:
        params["timeout"] = MAX_PROBE_SECONDS


def _validate_probe_limits(params: Mapping[str, JsonValue]) -> None:
    """限制用户试跑的外部工作量，目录可见不等于允许无限抓取。"""
    if len(params) > MAX_PROBE_COLLECTION_ITEMS:
        raise ValueError(f"at most {MAX_PROBE_COLLECTION_ITEMS} probe parameters are allowed")
    for name, value in params.items():
        _validate_value_limits(name, value)
        if _is_page_parameter(name):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 1 <= value <= MAX_PROBE_PAGE
            ):
                raise ValueError(
                    f"parameter {name!r} must be an integer between 1 and {MAX_PROBE_PAGE} for a probe"
                )
        if _is_row_limit_parameter(name):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 1 <= value <= MAX_SAMPLE_ROWS
            ):
                raise ValueError(
                    f"parameter {name!r} must be an integer between 1 and {MAX_SAMPLE_ROWS} for a probe"
                )
        if name.casefold() == "timeout":
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0 < value <= MAX_PROBE_SECONDS
            ):
                raise ValueError(
                    f"parameter {name!r} must be a number between 0 and {MAX_PROBE_SECONDS:g} for a probe"
                )
    _validate_date_window(params)


def _is_page_parameter(name: str) -> bool:
    return "page" in name.casefold()


def _is_row_limit_parameter(name: str) -> bool:
    return name.casefold() in _PROBE_ROW_LIMIT_PARAMETERS


def _validate_date_window(params: Mapping[str, JsonValue]) -> None:
    parsed: dict[str, date] = {}
    for name, value in params.items():
        if name.casefold() not in _PROBE_DATE_PARAMETERS:
            continue
        if not isinstance(value, str):
            raise ValueError(f"parameter {name!r} must be a YYYYMMDD or YYYY-MM-DD date")
        parsed[name.casefold()] = _parse_probe_date(name, value)

    start = parsed.get("start_date") or parsed.get("begin_date")
    end = parsed.get("end_date")
    if start is not None and end is not None:
        if end < start:
            raise ValueError("end_date must not be before start_date")
        if (end - start).days > MAX_PROBE_DATE_WINDOW_DAYS:
            raise ValueError(
                f"probe date window must not exceed {MAX_PROBE_DATE_WINDOW_DAYS} days"
            )


def _parse_probe_date(name: str, value: str) -> date:
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"parameter {name!r} must be a YYYYMMDD or YYYY-MM-DD date")


def _validate_value_limits(name: str, value: JsonValue) -> None:
    if isinstance(value, str) and len(value) > MAX_PROBE_STRING_LENGTH:
        raise ValueError(f"parameter {name!r} exceeds {MAX_PROBE_STRING_LENGTH} characters")
    if isinstance(value, list):
        if len(value) > MAX_PROBE_COLLECTION_ITEMS:
            raise ValueError(f"parameter {name!r} has too many values")
        for item in value:
            _validate_value_limits(name, item)
    elif isinstance(value, dict):
        if len(value) > MAX_PROBE_COLLECTION_ITEMS:
            raise ValueError(f"parameter {name!r} has too many fields")
        for item in value.values():
            _validate_value_limits(name, item)


def _validate_and_bind(
    target: Callable[..., object], signature: inspect.Signature, params: Mapping[str, JsonValue]
) -> None:
    allowed = {
        item.name
        for item in signature.parameters.values()
        if item.kind not in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD)
    }
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ValueError(f"unknown parameters: {', '.join(unknown)}")
    try:
        signature.bind(**params)
    except TypeError as exc:
        raise ValueError(f"invalid parameters: {exc}") from exc
    _ = target


def _is_json_value(value: object) -> bool:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False


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
