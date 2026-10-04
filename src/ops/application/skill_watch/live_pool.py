"""监测候选缓存与模型调用预算，不依赖模拟账户。"""
from __future__ import annotations
from typing import Any
DEFAULT_WATCH_LLM_TIMEOUT_SEC = 1800.0
MIN_WATCH_LLM_TIMEOUT_SEC = 120.0
MAX_WATCH_LLM_TIMEOUT_SEC = 1800.0

def save_live_pool(
    store: Any,
    *,
    slug: str,
    trade_date: str,
    picks: list[dict[str, Any]],
) -> None:
    """兼容旧调用名；实际写入统一监察池。"""
    if store is None:
        return
    from src.ops.application.unified_monitor_pool import replace_candidate_feed

    replace_candidate_feed(
        store,
        slug=slug,
        trade_date=str(trade_date or "").strip(),
        feed=f"skill_watch:{str(slug or '').strip()}",
        candidates=picks,
    )


def load_live_pool(
    store: Any,
    *,
    slug: str,
    trade_date: str,
) -> list[dict[str, Any]] | None:
    """兼容旧读取名；只返回统一池的非持仓投影。"""
    if store is None or not hasattr(store, "get_setting"):
        return None
    raw = store.get_setting(f"unified_monitor_pool:{str(slug).strip()}", None)
    if isinstance(raw, dict) and str(raw.get("trade_date") or "") != str(trade_date):
        return None
    if raw is None:
        return None
    from src.ops.application.unified_monitor_pool import get_unified_monitor_pool

    snapshot = get_unified_monitor_pool(store, slug=slug, trade_date=str(trade_date))
    if snapshot.get("trade_date") != str(trade_date):
        return None
    return [
        dict(item)
        for item in snapshot.get("items") or []
        if isinstance(item, dict) and item.get("bucket") != "position"
    ]


def watch_llm_timeout_sec(config: dict[str, Any]) -> float:
    """监测摘要模型允许慢推理；默认给足 30 分钟单次调用预算。"""
    try:
        value = float(config.get("llm_timeout_sec") or DEFAULT_WATCH_LLM_TIMEOUT_SEC)
    except (TypeError, ValueError):
        return DEFAULT_WATCH_LLM_TIMEOUT_SEC
    if value <= 0:
        return DEFAULT_WATCH_LLM_TIMEOUT_SEC
    return max(MIN_WATCH_LLM_TIMEOUT_SEC, min(value, MAX_WATCH_LLM_TIMEOUT_SEC))
