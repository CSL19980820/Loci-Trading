"""AkShare 探测参数校验与类型归一。"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from inspect import Parameter
import inspect
import json
import math
import re

from src.market.infrastructure.akshare_probe_result import JsonValue, json_safe

MAX_SAMPLE_ROWS = 5
MAX_PROBE_PAGE = 5
MAX_PROBE_STRING_LENGTH = 128
MAX_PROBE_COLLECTION_ITEMS = 20
MAX_PROBE_DATE_WINDOW_DAYS = 31
MAX_PROBE_SECONDS = 8.0
MAX_PROBE_JSON_DEPTH = 4
MAX_PROBE_JSON_NODES = 128
MAX_PROBE_PARAMS_BYTES = 16 * 1024
_PROBE_DATE_PARAMETERS = frozenset(
    {"date", "trade_date", "start_date", "begin_date", "end_date"}
)
_PROBE_ROW_LIMIT_PARAMETERS = frozenset({"limit", "size", "count", "num", "top"})


def _annotation_text(annotation: object) -> str | None:
    if annotation is Parameter.empty:
        return None
    if isinstance(annotation, str):
        return annotation
    return inspect.formatannotation(annotation)


def _probe_sample(name: str, value: object) -> JsonValue:
    """保留上游默认值，同时给可能大批量的分页接口一个小样本。"""
    if _is_page_parameter(name) and isinstance(value, int) and not isinstance(value, bool):
        return min(max(value, 1), MAX_PROBE_PAGE)
    return json_safe(value)


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
