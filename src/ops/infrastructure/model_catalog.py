"""LLM 模型目录：规范化、合并发现结果、派生对外字段。

``models_json`` 形状从旧 ``string[]`` 升为对象数组；读时兼容两种形态。
对外同时给 ``model_catalog``（全量元数据）与 ``models``（仅启用 id，兼容旧选择器）。
"""
from __future__ import annotations

from typing import Any

SOURCE_DISCOVERED = "discovered"
SOURCE_MANUAL = "manual"


def _positive_int(value: Any) -> int | None:
    if value is None or value is False:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def model_entry(
    model_id: str,
    *,
    name: str = "",
    enabled: bool = True,
    context_window: int | None = None,
    max_output_tokens: int | None = None,
    source: str = SOURCE_MANUAL,
) -> dict[str, Any]:
    mid = str(model_id).strip()
    display = str(name or "").strip() or mid
    src = SOURCE_DISCOVERED if source == SOURCE_DISCOVERED else SOURCE_MANUAL
    return {
        "id": mid,
        "name": display,
        "enabled": bool(enabled),
        "context_window": _positive_int(context_window),
        "max_output_tokens": _positive_int(max_output_tokens),
        "source": src,
    }


def normalize_models(raw: Any) -> list[dict[str, Any]]:
    """把旧 string[] / 半成品对象列表统一成目录条目。"""
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            mid = item.strip()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            out.append(model_entry(mid, source=SOURCE_DISCOVERED))
            continue
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        enabled = item.get("enabled", True)
        out.append(
            model_entry(
                mid,
                name=str(item.get("name") or ""),
                enabled=bool(enabled) if enabled is not None else True,
                context_window=item.get("context_window"),
                max_output_tokens=item.get("max_output_tokens"),
                source=str(item.get("source") or SOURCE_MANUAL),
            )
        )
    return out


def enabled_model_ids(catalog: list[dict[str, Any]]) -> list[str]:
    return [str(item["id"]) for item in catalog if item.get("enabled")]


def find_model_entry(
    catalog: list[dict[str, Any]], model_id: str
) -> dict[str, Any] | None:
    mid = str(model_id or "").strip()
    if not mid:
        return None
    for item in catalog:
        if item.get("id") == mid:
            return item
    return None


def ensure_default_in_catalog(
    catalog: list[dict[str, Any]], default_model: str
) -> list[dict[str, Any]]:
    """默认模型若不在目录里，补一条 manual（启用）。"""
    mid = str(default_model or "").strip()
    if not mid:
        return catalog
    if find_model_entry(catalog, mid):
        return catalog
    return [*catalog, model_entry(mid, source=SOURCE_MANUAL)]


def merge_discovered(
    existing: list[dict[str, Any]],
    discovered: list[dict[str, Any]] | list[str],
) -> list[dict[str, Any]]:
    """按 id 合并发现结果；保留用户改过的启用/上下文/名称。

    未再返回的 discovered 项保留；manual 永不因拉取删除。
    新发现项默认 enabled；若发现接口带回 context_window 且本地为空则填入。
    """
    base = normalize_models(existing)
    by_id = {str(item["id"]): dict(item) for item in base}
    order = [str(item["id"]) for item in base]

    for raw in discovered:
        if isinstance(raw, str):
            entry = model_entry(raw, source=SOURCE_DISCOVERED)
        elif isinstance(raw, dict) and raw.get("id"):
            entry = model_entry(
                str(raw["id"]),
                name=str(raw.get("name") or ""),
                context_window=raw.get("context_window"),
                max_output_tokens=raw.get("max_output_tokens"),
                source=SOURCE_DISCOVERED,
            )
        else:
            continue
        mid = entry["id"]
        if mid in by_id:
            current = by_id[mid]
            # 用户改过的字段优先；发现侧只补空的上下文/输出上限。
            if current.get("context_window") is None and entry.get("context_window"):
                current["context_window"] = entry["context_window"]
            if current.get("max_output_tokens") is None and entry.get("max_output_tokens"):
                current["max_output_tokens"] = entry["max_output_tokens"]
            if current.get("name") in ("", current.get("id")) and entry.get("name"):
                current["name"] = entry["name"]
            if current.get("source") != SOURCE_MANUAL:
                current["source"] = SOURCE_DISCOVERED
            by_id[mid] = current
        else:
            by_id[mid] = entry
            order.append(mid)

    return [by_id[mid] for mid in order if mid in by_id]


def present_provider_models(raw_models: Any) -> dict[str, Any]:
    """给 API 行用：归一化后拆出 catalog + enabled ids。"""
    catalog = normalize_models(raw_models)
    return {
        "model_catalog": catalog,
        "models": enabled_model_ids(catalog),
    }
