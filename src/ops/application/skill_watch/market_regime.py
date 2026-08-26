"""龙空龙市场闸门：只判断是否允许进入进攻窗口。

这是实时/前向验证规则，不是历史回测策略。数据缺失时默认拒绝开仓，
避免把悟道快照不完整误判成可进攻。
"""
from __future__ import annotations


def _wudao_keys():
    """悟道键名表。**延迟导入**：``src.intel.__init__`` 会反向 import ``src.ops``，
    模块级导入直接成环（ImportError: partially initialized module）。
    """
    from src.intel.application import wudao_keys

    return wudao_keys


from collections.abc import Mapping
from datetime import datetime
import time
from typing import Any, Literal
from zoneinfo import ZoneInfo

from src.ops.application.skill_watch import payload as pl
from src.ops.application.skill_watch.defaults import DEFAULT_GATE_PARAMS

RegimeState = Literal["dragon", "observe", "empty"]


def _ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return value / 100.0 if abs(value) > 1.5 else value


def _scale_100(value: float | None) -> float | None:
    if value is None:
        return None
    return value * 100.0 if abs(value) <= 1.5 else value


def _normalize_theme_strength(value: float | None) -> float | None:
    """题材强度：旧夹具 0-100；开盘啦盘中强度常为数千，压到同量级再比阈值。"""
    if value is None:
        return None
    if value > 200:
        return min(100.0, value / 150.0)
    return _scale_100(value)


def _ladder_height(
    payload: Any,
    *,
    root: Mapping[str, Any] | None = None,
    maps: list[Mapping[str, Any]] | None = None,
) -> float | None:
    """只认最高板 / boardSummary / 成分连板数，避免把晋级率误读成高度。"""
    direct = pl.metric(payload, "height", root=root, maps=maps)
    if direct is not None:
        return direct
    root_map = dict(root) if root is not None else pl.structured(payload)
    maps_list = maps if maps is not None else pl.walk_maps(root_map)
    levels: list[float] = []
    for mapping in maps_list:
        summary = mapping.get("boardSummary") or mapping.get("board_summary")
        if isinstance(summary, list):
            for item in summary:
                if isinstance(item, dict):
                    level = pl.number(item.get("level"))
                    if level is not None:
                        levels.append(level)
    for _code, row in pl.rows_by_code(payload, limit=200).items():
        level = pl.field(row, "ladder_level")
        if level is not None:
            levels.append(level)
    return max(levels) if levels else None


def _tape_metadata(payload: Any, lane: str) -> tuple[dict[str, Any], list[str]]:
    """读取 market tape 桥附带的来源，不改变旧 payload 解析语义。"""
    if not isinstance(payload, Mapping):
        return {"lane": lane, "provider_id": None}, []
    provenance = payload.get("provenance")
    if not isinstance(provenance, Mapping):
        provenance = {}
    provider_id = str(
        payload.get("provider_id") or provenance.get("provider_id") or ""
    ).strip() or None
    raw_warnings = [
        str(item).strip()
        for item in (
            provenance.get("warnings")
            if isinstance(provenance.get("warnings"), list)
            else payload.get("warnings")
            if isinstance(payload.get("warnings"), list)
            else []
        )
        if str(item).strip()
    ]
    # 非实时/日期备注由 freshness 统一处理，不把同日缓存误报成工具错误。
    quality = [
        item
        for item in raw_warnings
        if item not in {"非实时快照", "日期错位", "非当日", "数据日新于请求日"}
    ]
    if bool(payload.get("degraded")) or bool(provenance.get("degraded")):
        quality.append("degraded")
    return (
        {
            "lane": lane,
            "provider_id": provider_id,
            "degraded": bool(payload.get("degraded") or provenance.get("degraded")),
            "stale": bool(provenance.get("stale")),
            "from_cache": bool(provenance.get("from_cache")),
            "warnings": list(dict.fromkeys(raw_warnings)),
            "attempts": provenance.get("attempts") or [],
        },
        [f"{lane}:{item}" for item in dict.fromkeys(quality)],
    )


def _is_hard_warning(warning: str) -> bool:
    """错日 / 工具失败 / 无效载荷 → 硬空仓；其余质量提示视为软降级。"""
    text = str(warning or "").strip()
    if not text:
        return False
    if text.endswith(":tool_error") or text.endswith(":invalid_payload"):
        return True
    return any(
        token in text
        for token in ("date_mismatch", "stale_or_mismatch", "freshness:stale")
    )


def evaluate_market_gate(
    emotion: Any,
    ladder: Any,
    themes: Any,
    *,
    trade_date: str = "",
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """把三类实时快照压成可审计的龙/空/观察结果。"""
    config = {**DEFAULT_GATE_PARAMS, **dict(params or {})}
    emotion_root = pl.structured(emotion)
    ladder_root = pl.structured(ladder)
    themes_root = pl.structured(themes)
    emotion_maps = pl.walk_maps(emotion_root)
    ladder_maps = pl.walk_maps(ladder_root)
    themes_maps = pl.walk_maps(themes_root)
    raw_theme = pl.max_metric(
        themes, "theme_strength", root=themes_root, maps=themes_maps
    )
    # seal/limit_down/breadth 已在 payload.metric 合成比率（0-1）；main_net_yi 为亿元
    ladder_height = _ladder_height(ladder, root=ladder_root, maps=ladder_maps)
    emotion_height = pl.metric(
        emotion, "height", root=emotion_root, maps=emotion_maps
    )
    metrics: dict[str, float | None] = {
        "promotion_rate": _ratio(
            pl.metric(emotion, "promotion_rate", root=emotion_root, maps=emotion_maps)
        ),
        "broken_rate": _ratio(
            pl.metric(emotion, "broken_rate", root=emotion_root, maps=emotion_maps)
        ),
        "seal_rate": _ratio(
            pl.metric(emotion, "seal_rate", root=emotion_root, maps=emotion_maps)
        ),
        "limit_down_rate": _ratio(
            pl.metric(emotion, "limit_down_rate", root=emotion_root, maps=emotion_maps)
        ),
        "breadth": _ratio(
            pl.metric(emotion, "breadth", root=emotion_root, maps=emotion_maps)
        ),
        "temperature": _scale_100(
            pl.metric(emotion, "temperature", root=emotion_root, maps=emotion_maps)
        ),
        "limit_up_count": pl.metric(
            emotion, "limit_up_count", root=emotion_root, maps=emotion_maps
        ),
        "limit_down_count": pl.metric(
            emotion, "limit_down_count", root=emotion_root, maps=emotion_maps
        ),
        "main_net_yi": pl.metric(
            emotion, "main_net_yi", root=emotion_root, maps=emotion_maps
        ),
        # 梯队高度：优先连板梯队；情绪快照 summary.highestBoard 作兜底（悟道同字段）
        # 不用 `or`：高度为 0 时仍算有效，避免被 emotion 兜底冲掉
        "height": emotion_height if ladder_height is None else ladder_height,
        # 开盘啦 strength 常为上千；闸门比较仍用可读 0-100 量级
        "theme_strength": _normalize_theme_strength(raw_theme),
    }
    tape_meta: dict[str, dict[str, Any]] = {}
    tape_quality_warnings: list[str] = []
    for lane, payload in (
        ("market_emotion", emotion),
        ("limit_up_pool", ladder),
        ("theme_board", themes),
    ):
        meta, quality = _tape_metadata(payload, lane)
        tape_meta[lane] = meta
        tape_quality_warnings.extend(quality)
    provider_ids = [
        str(meta["provider_id"])
        for meta in tape_meta.values()
        if str(meta.get("provider_id") or "").strip()
    ]
    unique_provider_ids = list(dict.fromkeys(provider_ids))
    provider_warnings = ["mixed_provider"] if len(unique_provider_ids) > 1 else []
    warnings = [
        *pl.quality_warnings(emotion, "emotion"),
        *pl.quality_warnings(ladder, "ladder"),
        *pl.quality_warnings(themes, "themes"),
        *tape_quality_warnings,
    ]
    freshness = pl.merge_freshness(
        pl.extract_freshness(emotion, requested=trade_date),
        pl.extract_freshness(ladder, requested=trade_date),
        pl.extract_freshness(themes, requested=trade_date),
        requested=trade_date,
    )
    # 日期错位 / 非当日：按空仓处理，避免把昨收情绪当盘中进攻
    if freshness.get("stale"):
        warnings.append("freshness:stale_or_mismatch")
    required = ("promotion_rate", "height", "theme_strength")
    missing = [name for name in required if metrics[name] is None]
    score = 0
    reasons: list[str] = []

    promotion = metrics["promotion_rate"]
    broken = metrics["broken_rate"]
    height = metrics["height"]
    theme_strength = metrics["theme_strength"]
    breadth = metrics["breadth"]
    temperature = metrics["temperature"]

    if promotion is not None:
        if promotion >= float(config["promotion_attack"]):
            score += 2
            reasons.append("晋级率支持")
        elif promotion <= float(config["promotion_empty"]):
            score -= 2
            reasons.append("晋级率低")
    if broken is not None:
        if broken >= float(config["broken_empty"]):
            score -= 2
            reasons.append("炸板率偏高")
        elif broken <= float(config["broken_attack_max"]):
            score += 1
            reasons.append("炸板率可控")
    if height is not None:
        if height >= float(config["min_height_attack"]):
            score += 1
            reasons.append("梯队有高度")
        elif height <= 1:
            score -= 1
            reasons.append("梯队无高度")
    if theme_strength is not None:
        if theme_strength >= float(config["theme_strength_attack"]):
            score += 1
            reasons.append("主线强度支持")
        elif theme_strength < float(config["theme_strength_empty"]):
            score -= 1
            reasons.append("主线强度不足")
    if breadth is not None:
        if breadth >= float(config["breadth_attack"]):
            score += 1
        elif breadth <= float(config["breadth_empty"]):
            score -= 1
    if temperature is not None:
        if temperature >= float(config["temperature_attack"]):
            score += 1
        elif temperature <= float(config["temperature_empty"]):
            score -= 1

    up_count = metrics["limit_up_count"]
    down_count = metrics["limit_down_count"]
    hard_risk = (
        (broken is not None and broken >= float(config["broken_empty"]))
        or (promotion is not None and promotion <= float(config["promotion_empty"]))
        or (
            up_count is not None
            and down_count is not None
            and up_count > 0
            and down_count >= up_count * 2
        )
    )
    hard_warnings = [w for w in warnings if _is_hard_warning(str(w))]
    soft_warnings = [w for w in warnings if not _is_hard_warning(str(w))]
    tool_errors = [w for w in warnings if str(w).endswith(":tool_error")]
    if freshness.get("stale"):
        state: RegimeState = "empty"
        reasons.insert(0, "数据非当日实时，按空仓处理")
    elif tool_errors and len(missing) >= 2:
        state = "empty"
        reasons.insert(0, "市场快照调用失败，按空仓处理")
    elif missing or hard_warnings:
        state = "empty"
        reasons.insert(0, "关键数据不完整，按空仓处理")
    elif soft_warnings:
        # 软降级：可继续出观察，禁止进攻（与硬空仓区分）
        if hard_risk or score <= -2:
            state = "empty"
            reasons.insert(0, "软降级且风险偏空，按空仓处理")
        else:
            state = "observe"
            reasons.insert(0, "数据软降级，暂不进攻")
    elif hard_risk or score <= -2:
        state = "empty"
    elif score >= 3:
        state = "dragon"
    else:
        state = "observe"

    labels = {
        "dragon": ("龙", "进攻窗口"),
        "observe": ("观察", "信号混合，暂不扩张"),
        "empty": ("空", "空仓窗口"),
    }
    mode, label = labels[state]
    effective_day = str(freshness.get("actual_trade_date") or trade_date or "")
    return {
        "state": state,
        "mode": mode,
        "label": label,
        "entry_allowed": state == "dragon",
        "trade_date": effective_day or trade_date,
        "requested_trade_date": trade_date,
        "score": score,
        "data_status": "degraded" if missing or warnings or freshness.get("stale") else "ok",
        "missing": missing,
        "quality_warnings": list(dict.fromkeys(warnings)),
        "hard_warnings": list(dict.fromkeys(hard_warnings)),
        "soft_warnings": list(dict.fromkeys(soft_warnings)),
        "provider_warnings": provider_warnings,
        "provider_id": unique_provider_ids[0] if len(unique_provider_ids) == 1 else (
            "mixed" if unique_provider_ids else None
        ),
        "provider_ids": {
            lane: meta.get("provider_id") for lane, meta in tape_meta.items()
        },
        "tape_provenance": tape_meta,
        "freshness": freshness,
        "reasons": list(dict.fromkeys(reasons)) or ["暂无足够证据"],
        "reason": "；".join(dict.fromkeys(reasons)) or "暂无足够证据",
        "metrics": metrics,
        "source_counts": {
            "ladder_rows": pl.row_count(ladder),
            "theme_rows": pl.row_count(themes),
        },
    }


def disabled_market_gate(trade_date: str | None = None) -> dict[str, Any]:
    """用户关掉 market_gate 段：与纸面监测一致 fail-closed，禁开仓。"""
    day = trade_date or today_trade_date()
    reason = "龙空龙闸门已关闭，默认禁开仓"
    return {
        "state": "empty",
        "mode": "空",
        "label": "空仓窗口",
        "entry_allowed": False,
        "trade_date": day,
        "score": 0,
        "data_status": "disabled",
        "missing": [],
        "quality_warnings": ["market_gate_disabled"],
        "reasons": [reason],
        "reason": reason,
        "metrics": {},
        "source_counts": {},
    }


def today_trade_date() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


#: 三件套快照短缓存：纸面闸门与 skill_watch 扫描共享，按日+固定工具参数键。
#: 与纸面闸门结论 TTL 对齐，避免一侧改值叠乘语义漂移。
MARKET_SNAPSHOT_TTL_SEC = 90.0
_SNAPSHOT_TTL_SEC = MARKET_SNAPSHOT_TTL_SEC
_SNAPSHOT_CACHE: dict[str, tuple[float, tuple[Any, Any, Any]]] = {}

_SNAPSHOT_LADDER_ARGS = {
    "maxRowsPerLevel": 10,
    "includeFirstBoard": False,
    "format": "json",
    "detailLevel": "standard",
}
_SNAPSHOT_THEME_ARGS = {
    "limit": 20,
    "includeBoomReason": False,
    "format": "json",
    "detailLevel": "standard",
}


def clear_market_snapshot_cache() -> None:
    """测试或强制刷新时清空 emotion/ladder/themes 短缓存。"""
    _SNAPSHOT_CACHE.clear()


def _snapshot_cache_key(day: str) -> str:
    return (
        f"{day}|ladder:maxRows={_SNAPSHOT_LADDER_ARGS['maxRowsPerLevel']}"
        f"|themes:limit={_SNAPSHOT_THEME_ARGS['limit']}"
        f"|boom={int(bool(_SNAPSHOT_THEME_ARGS['includeBoomReason']))}"
    )


def fetch_market_snapshot(
    call_tool: Any | None = None,
    *,
    trade_date: str | None = None,
    force_refresh: bool = False,
) -> tuple[Any, Any, Any]:
    """获取闸门和候选扫描共用的三份快照，避免一次监测重复扣配额。"""
    day = trade_date or today_trade_date()
    cache_key = _snapshot_cache_key(day)
    now = time.monotonic()
    if not force_refresh:
        cached = _SNAPSHOT_CACHE.get(cache_key)
        if cached and (now - cached[0]) < _SNAPSHOT_TTL_SEC:
            emotion, ladder, themes = cached[1]
            return (
                dict(emotion) if isinstance(emotion, dict) else emotion,
                dict(ladder) if isinstance(ladder, dict) else ladder,
                dict(themes) if isinstance(themes, dict) else themes,
            )

    if call_tool is None:
        from src.market import make_legacy_tape_call

        call_tool = make_legacy_tape_call()
    emotion = call_tool(
        "short_term_emotion",
           _wudao_keys().with_date(
      "short_term_emotion", day, format="json", detailLevel="standard"
 ),
    )
    ladder = call_tool(
        "limit_up_ladder",
          _wudao_keys().with_date("limit_up_ladder", day, **_SNAPSHOT_LADDER_ARGS),
    )
    themes = call_tool(
        "theme_intraday_capital",
           _wudao_keys().with_date("theme_intraday_capital", day, **_SNAPSHOT_THEME_ARGS),
    )
    expired = [k for k, (ts, _) in _SNAPSHOT_CACHE.items() if now - ts >= _SNAPSHOT_TTL_SEC]
    for stale in expired:
        _SNAPSHOT_CACHE.pop(stale, None)
    _SNAPSHOT_CACHE[cache_key] = (
        now,
        (
            dict(emotion) if isinstance(emotion, dict) else emotion,
            dict(ladder) if isinstance(ladder, dict) else ladder,
            dict(themes) if isinstance(themes, dict) else themes,
        ),
    )
    return emotion, ladder, themes


def scan_market_gate(
    call_tool: Any | None = None,
    *,
    trade_date: str | None = None,
    params: Mapping[str, Any] | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """通过统一 tape 入口获取一次市场闸门快照。"""
    day = trade_date or today_trade_date()
    emotion, ladder, themes = fetch_market_snapshot(
        call_tool, trade_date=day, force_refresh=force_refresh
    )
    result = evaluate_market_gate(
        emotion,
        ladder,
        themes,
        trade_date=day,
        params=params,
    )
    result["tool_status"] = {
        "short_term_emotion": not pl.tool_failed(emotion),
        "limit_up_ladder": not pl.tool_failed(ladder),
        "theme_intraday_capital": not pl.tool_failed(themes),
    }
    return result


__all__ = [
    "DEFAULT_GATE_PARAMS",
    "MARKET_SNAPSHOT_TTL_SEC",
    "RegimeState",
    "clear_market_snapshot_cache",
    "disabled_market_gate",
    "evaluate_market_gate",
    "fetch_market_snapshot",
    "scan_market_gate",
    "today_trade_date",
]
