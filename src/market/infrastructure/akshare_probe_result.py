"""AkShare 试跑结果的 JSON 安全摘要。"""
from __future__ import annotations

from datetime import date, datetime
from itertools import islice
import math

from src.market.domain.column_glossary import gloss_column

try:
    import pandas as pd
except ImportError:  # pragma: no cover - 项目运行环境已安装 pandas
    pd = None  # type: ignore[assignment]


JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
MAX_RESULT_COLUMNS = 40
MAX_RESULT_FIELD_BYTES = 256
MAX_RESULT_COLLECTION_ITEMS = 20
MAX_RESULT_DEPTH = 4
MAX_RESULT_NODES = 160
_TRUNCATED = "<truncated>"


def summarize_probe_result(
    value: object,
    *,
    max_sample_rows: int,
) -> dict[str, JsonValue]:
    """把任意受控接口返回值限制为可展示的小型 JSON 结果。"""
    if pd is not None and isinstance(value, pd.DataFrame):
        records = value.iloc[:max_sample_rows, :MAX_RESULT_COLUMNS].to_dict(orient="records")
        columns = _probe_columns(value.columns)
        return {
            "rows": int(len(value.index)),
            "columns": columns,
            "columns_detail": glossed_columns(columns),
            "sample": _probe_samples(records),
            "truncated": len(value.index) > max_sample_rows,
        }
    if isinstance(value, list):
        columns = _list_columns(value)
        return {
            "rows": len(value),
            "columns": columns,
            "columns_detail": glossed_columns(columns),
            "sample": _probe_samples(value[:max_sample_rows]),
            "truncated": len(value) > max_sample_rows,
        }
    if isinstance(value, dict):
        columns = _probe_columns(value)
        return {
            "rows": 1,
            "columns": columns,
            "columns_detail": glossed_columns(columns),
            "sample": _probe_samples([value]),
            "truncated": False,
        }
    return {
        "rows": 1,
        "columns": [],
        "columns_detail": [],
        "sample": _probe_samples([value]),
        "truncated": False,
    }


def glossed_columns(columns: list[str]) -> list[dict[str, str]]:
    """给已截断的列名列表补中英对照；沿用 ``columns`` 的 40 列上限。"""
    return [gloss_column(column) for column in columns]


def _probe_samples(values: list[object]) -> list[JsonValue]:
    budget = [MAX_RESULT_NODES]
    return [_probe_json_safe(value, budget=budget) for value in values]


def _list_columns(values: list[object]) -> list[str]:
    columns: list[str] = []
    for value in values[:MAX_RESULT_COLLECTION_ITEMS]:
        if isinstance(value, dict):
            for key in value:
                column = _truncate_text(str(key))
                if column not in columns:
                    columns.append(column)
                if len(columns) >= MAX_RESULT_COLUMNS:
                    return columns
    return columns


def _probe_columns(values: object) -> list[str]:
    return [_truncate_text(str(value)) for value in islice(values, MAX_RESULT_COLUMNS)]  # type: ignore[arg-type]


def _probe_json_safe(value: object, *, budget: list[int], depth: int = 0) -> JsonValue:
    if budget[0] <= 0 or depth > MAX_RESULT_DEPTH:
        return _TRUNCATED
    budget[0] -= 1
    if isinstance(value, str):
        return _truncate_text(value)
    if isinstance(value, (list, tuple)):
        return [
            _probe_json_safe(item, budget=budget, depth=depth + 1)
            for item in islice(value, MAX_RESULT_COLLECTION_ITEMS)
        ]
    if isinstance(value, dict):
        return {
            _truncate_text(str(key)): _probe_json_safe(item, budget=budget, depth=depth + 1)
            for key, item in islice(value.items(), MAX_RESULT_COLLECTION_ITEMS)
        }
    if pd is not None and _is_missing(value):
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _probe_json_safe(item(), budget=budget, depth=depth + 1)
        except (TypeError, ValueError):
            pass
    return _truncate_text(str(value))


def _truncate_text(value: str) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= MAX_RESULT_FIELD_BYTES:
        return value
    return encoded[:MAX_RESULT_FIELD_BYTES].decode("utf-8", errors="ignore")


def json_safe(value: object) -> JsonValue:
    if pd is not None and _is_missing(value):
        return None
    if value is None or isinstance(value, bool) or isinstance(value, str):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return json_safe(item())
        except (TypeError, ValueError):
            pass
    return str(value)


def _is_missing(value: object) -> bool:
    if isinstance(value, (list, tuple, dict)):
        return False
    missing = pd.isna(value)
    return isinstance(missing, bool) and missing
