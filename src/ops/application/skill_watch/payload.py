"""skill_watch 共用：悟道 MCP 返回体解析。

四个扫描器都要从同一批工具里挖「行、代码、指标、质量告警」。解析规则只写
一份，避免每个战法各写一套别名表后彼此判得不一样。
"""
from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import json
import math
import re
from typing import Any

_NON_TOKEN = re.compile(r"[^a-z0-9\u4e00-\u9fff]")

#: 各扫描器共享的字段别名。悟道同一语义在不同工具里叫法不一致。
ALIASES: dict[str, tuple[str, ...]] = {
    "promotion_rate": (
        "promotion_rate",
        "promotionRate",
        "streakPromotion",
        "firstToSecond",
        "secondPlusPromotion",
        "晋级率",
        "连板晋级率",
        "连板晋级",
    ),
    "broken_rate": (
        "broken_rate",
        "brokenRate",
        "brokenBoardRate",
        "broken_board_rate",
        "炸板率",
        "炸板",
    ),
    "breadth": (
        "breadth",
        "breadth_rate",
        "advance_rate",
        "上涨家数占比",
        "上涨比例",
        "市场宽度",
    ),
    "temperature": ("temperature", "market_temperature", "市场温度", "情绪温度"),
    "limit_up_count": (
        "limit_up_count",
        "limitUpCount",
        "sealedLimitUp",
        "涨停家数",
        "涨停",
    ),
    "limit_down_count": (
        "limit_down_count",
        "limitDownCount",
        "sealedLimitDown",
        "跌停家数",
        "跌停",
    ),
    "height": (
        "height",
        "max_height",
        "maxHeight",
        "highest_board",
        "highestBoard",
        "最高连板",
        "连板高度",
        "空间板",
    ),
    "theme_strength": ("strength", "theme_strength", "themeStrength", "板块强度", "题材强度"),
    "ladder_level": (
        "level",
        "board",
        "boards",
        "continueNum",
        "continue_num",
        "连板数",
        "板数",
    ),
    "main_net_amount": ("mainNetAmount", "main_net_amount", "主力净额", "主力净流入"),
    "pct_chg": ("pctChg", "pct_chg", "change_pct", "涨跌幅", "涨幅"),
}

#: 梯队层级这类字段挂在父节点上，成分行本身没有，向下继承。
LADDER_INHERIT_KEYS = ("level", "board", "boards", "连板数", "连板", "height")


@lru_cache(maxsize=4096)
def _normal_key_cached(text: str) -> str:
    return _NON_TOKEN.sub("", text.lower())


def normal_key(value: Any) -> str:
    return _normal_key_cached(str(value))


def number(value: Any) -> float | None:
    """把 ``"12.5%"`` / ``"1,024"`` 之类文本转成数字；不可解析返回 None。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def clean_code(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-6:] if len(digits) >= 6 else ""


#: MCP 返回体的信封字段。正文超限被截断时 JSON 解析必然失败，若此时把信封
#: 本身当结构化段返回，``extract_freshness`` 会从 ``quota.trade_date`` 里挖出
#: 一个「今天」，于是「取数失败」被读成「今天没有数据」，还带着当日戳。
_ENVELOPE_KEYS = ("tool", "server", "is_error", "unavailable", "text", "quota", "truncated")


def structured(payload: Any) -> dict[str, Any]:
    """取结构化段；只有文本时按 JSON 解析一次。

    解析不出结构化段时：MCP 信封返回 ``{}``（调用方据此判失败），
    调用方直接传进来的裸结构化 dict 才原样返回。
    """
    if not isinstance(payload, Mapping):
        return {}
    for key in ("structured", "structuredContent", "data", "result"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    text = str(payload.get("text") or "").strip()
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, Mapping):
            return dict(parsed)
    if any(key in payload for key in _ENVELOPE_KEYS):
        return {}
    return dict(payload)


def walk_maps(value: Any, *, depth: int = 0) -> list[Mapping[str, Any]]:
    """深度优先展开所有字典节点。悟道嵌套层级随工具与档位变化。"""
    if depth > 6:
        return []
    if isinstance(value, Mapping):
        result: list[Mapping[str, Any]] = [value]
        for child in value.values():
            result.extend(walk_maps(child, depth=depth + 1))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(walk_maps(child, depth=depth + 1))
        return result
    return []


def field(row: Mapping[str, Any], name: str) -> float | None:
    """按别名表从单行取数值。"""
    wanted = {normal_key(item) for item in ALIASES.get(name, (name,))}
    for key, value in row.items():
        if normal_key(key) in wanted:
            result = number(value)
            if result is not None:
                return result
    return None


def metric(
    payload: Any,
    name: str,
    *,
    root: Mapping[str, Any] | None = None,
    maps: list[Mapping[str, Any]] | None = None,
) -> float | None:
    """按别名表从整份载荷里找第一个可用数值。

    闸门热路径可传入已算好的 ``root`` / ``maps``，避免每个指标重新 walk。
    """
    root_map = dict(root) if root is not None else structured(payload)
    maps_list = maps if maps is not None else walk_maps(root_map)
    # 悟道 short_term_emotion：晋级率在 promotionRates 嵌套对象里
    if name == "promotion_rate":
        for mapping in maps_list:
            rates = mapping.get("promotionRates") or mapping.get("promotion_rates")
            if isinstance(rates, Mapping):
                for key in (
                    "streakPromotion",
                    "firstToSecond",
                    "secondPlusPromotion",
                    "晋级率",
                    "连板晋级",
                ):
                    value = number(rates.get(key))
                    if value is not None:
                        return value
    # 宽度：悟道给 {up,down,...}，合成上涨家数占比
    if name == "breadth":
        for mapping in maps_list:
            breadth = mapping.get("breadth")
            if isinstance(breadth, Mapping):
                up = number(breadth.get("up"))
                down = number(breadth.get("down"))
                if up is not None and down is not None and (up + down) > 0:
                    return up / (up + down)
    # 封板率：封住涨停 / 触及涨停（无触及则用 封住/(封住+炸板)）
    if name == "seal_rate":
        for mapping in maps_list:
            sealed = number(
                mapping.get("sealedLimitUp")
                or mapping.get("sealed_limit_up")
                or mapping.get("limit_up_count")
            )
            touched = number(
                mapping.get("touchedLimitUp") or mapping.get("touched_limit_up")
            )
            broken = number(
                mapping.get("brokenLimitUp") or mapping.get("broken_limit_up")
            )
            if sealed is not None and touched is not None and touched > 0:
                return sealed / touched
            if sealed is not None and broken is not None and (sealed + broken) > 0:
                return sealed / (sealed + broken)
    # 跌停占比：跌停 / (涨停+跌停)
    if name == "limit_down_rate":
        for mapping in maps_list:
            up = number(
                mapping.get("sealedLimitUp")
                or mapping.get("sealed_limit_up")
                or mapping.get("limitUpCount")
            )
            down = number(
                mapping.get("sealedLimitDown")
                or mapping.get("sealed_limit_down")
                or mapping.get("limitDownCount")
            )
            if up is not None and down is not None and (up + down) > 0:
                return down / (up + down)
    if name == "main_net_yi":
        for mapping in maps_list:
            yi = number(
                mapping.get("mainNetAmountYi")
                or mapping.get("main_net_amount_yi")
                or mapping.get("主力净流入亿")
            )
            if yi is not None:
                return yi
    for mapping in maps_list:
        # breadth 对象已在上面处理；这里跳过避免把 dict 当数
        if name == "breadth" and isinstance(mapping.get("breadth"), Mapping):
            continue
        result = field(mapping, name)
        if result is not None:
            return result
    return None


def max_metric(
    payload: Any,
    name: str,
    *,
    root: Mapping[str, Any] | None = None,
    maps: list[Mapping[str, Any]] | None = None,
) -> float | None:
    """取载荷中该指标的最大值（题材强度等多行场景）。"""
    root_map = dict(root) if root is not None else structured(payload)
    maps_list = maps if maps is not None else walk_maps(root_map)
    values: list[float] = []
    for mapping in maps_list:
        # 优先 rows 内的强度，避免误吃无关 score
        rows = mapping.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, Mapping):
                    value = field(row, name)
                    if value is not None:
                        values.append(value)
    if values:
        return max(values)
    return metric(payload, name, root=root_map, maps=maps_list)


def text_field(row: Mapping[str, Any], *names: str) -> str:
    wanted = {normal_key(item) for item in names}
    for key, value in row.items():
        if normal_key(key) in wanted and str(value or "").strip():
            return str(value).strip()
    return ""


def _walk_rows(
    value: Any,
    *,
    depth: int,
    inherit_keys: tuple[str, ...],
    inherited: Mapping[str, Any] | None,
) -> list[tuple[str, dict[str, Any]]]:
    if depth > 6:
        return []
    if isinstance(value, Mapping):
        context = dict(inherited or {})
        for key in inherit_keys:
            if key in value and number(value[key]) is not None:
                context.setdefault(key, value[key])
        result: list[tuple[str, dict[str, Any]]] = []
        code = clean_code(
            value.get("code") or value.get("stock_code") or value.get("stockCode")
        )
        if code:
            row = dict(value)
            for key, item in context.items():
                row.setdefault(key, item)
            result.append((code, row))
        for child in value.values():
            result.extend(
                _walk_rows(child, depth=depth + 1, inherit_keys=inherit_keys, inherited=context)
            )
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(
                _walk_rows(child, depth=depth + 1, inherit_keys=inherit_keys, inherited=inherited)
            )
        return result
    return []


def _row_richness(row: Mapping[str, Any]) -> int:
    """同一代码多份行时，优先保留带连板层级/行情字段的那份。"""
    score = 0
    for key in ("level", "continueNum", "continue_num", "board", "boards", "连板数"):
        if number(row.get(key)) is not None:
            score += 3
    for key in ("price", "changePercent", "pctChg", "tradeAmount", "primaryTheme"):
        if row.get(key) not in (None, ""):
            score += 1
    return score


def rows_by_code(
    payload: Any,
    *,
    limit: int = 24,
    inherit_keys: tuple[str, ...] = LADDER_INHERIT_KEYS,
) -> dict[str, dict[str, Any]]:
    """展平成 ``{6 位代码: 行}``；父节点上的连板层级会向下继承。"""
    rows: dict[str, dict[str, Any]] = {}
    for code, row in _walk_rows(
        structured(payload), depth=0, inherit_keys=inherit_keys, inherited=None
    ):
        previous = rows.get(code)
        if previous is None:
            if len(rows) >= limit:
                continue
            rows[code] = row
            continue
        if _row_richness(row) > _row_richness(previous):
            merged = dict(previous)
            merged.update(row)
            rows[code] = merged
    return rows


def row_count(payload: Any) -> int:
    for mapping in walk_maps(structured(payload)):
        for key in ("rows", "items", "levels", "ladder"):
            value = mapping.get(key)
            if isinstance(value, list):
                return len(value)
    return 0


def quality_warnings(payload: Any, label: str) -> list[str]:
    """悟道自报的质量问题 + 工具级错误，统一加前缀便于定位来源。"""
    if not isinstance(payload, Mapping):
        return [f"{label}:invalid_payload"]
    warnings: list[str] = []
    if payload.get("is_error"):
        warnings.append(f"{label}:tool_error")
    for source in (payload, structured(payload)):
        for key in ("qualityWarnings", "quality_warnings", "partialErrors", "partial_errors"):
            value = source.get(key)
            if isinstance(value, list):
                warnings.extend(f"{label}:{item}" for item in value if str(item).strip())
            elif value:
                warnings.append(f"{label}:{value}")
    return list(dict.fromkeys(warnings))


def normalize_trade_date(value: Any) -> str:
    """``20260807`` / ``2026-08-07`` → ISO 日；无法识别返回空串。"""
    text = re.sub(r"\D", "", str(value or ""))
    if len(text) >= 8 and text[:8].isdigit():
        raw = text[:8]
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return ""


def extract_freshness(payload: Any, *, requested: str = "") -> dict[str, Any]:
    """读悟道 ``actualTradeDate`` / ``dateStatus`` / ``snapshotTime`` / ``isRealtime``。

    官方约定（MCP 总则）：
    - ``dateStatus=mismatch`` 或 qualityWarnings 含 ``date_mismatch`` → 不得把实际数据
      说成请求日；
    - ``tradeDate ≠ requestedDate`` 时须说明；
    - ``short_term_emotion`` 盘中会变，须对照 ``snapshotTime``；
    - ``theme_intraday_capital.boomReason/boomDate`` 常是催化叙事（可跨日），**不能**当
      交易日字段，也禁止把嵌套 ``date`` / ``prevDate`` / ``boomDate`` 当成 actual。
    - 晋级率只用 ``short_term_emotion``，勿读梯队 ``emotionMetrics.prevDate``。
    """
    root = structured(payload)
    actual = ""
    status = ""
    snapshot = ""
    is_realtime: bool | None = None

    def _pick_actual(mapping: Mapping[str, Any]) -> str:
        # 只认明确交易日键；禁止 date/boomDate/prevDate（易掺入昨催化）
        return normalize_trade_date(
            mapping.get("actualTradeDate")
            or mapping.get("actual_trade_date")
            or mapping.get("tradeDate")
            or mapping.get("trade_date")
        )

    def _pick_freshness_flags(mapping: Mapping[str, Any]) -> None:
        nonlocal is_realtime
        if is_realtime is not None:
            return
        box = mapping.get("dataFreshness") or mapping.get("data_freshness")
        if isinstance(box, Mapping) and "isRealtime" in box:
            is_realtime = bool(box.get("isRealtime"))
        elif "isRealtime" in mapping:
            is_realtime = bool(mapping.get("isRealtime"))

    # 先扫顶层与 meta（深度浅），再退回 walk；始终忽略 boom/prev 日期键
    top_maps: list[Mapping[str, Any]] = []
    if isinstance(root, Mapping):
        top_maps.append(root)
        meta = root.get("meta") or root.get("standard")
        if isinstance(meta, Mapping):
            top_maps.append(meta)
            nested = meta.get("dataFreshness") or meta.get("standard")
            if isinstance(nested, Mapping):
                top_maps.append(nested)
        data = root.get("data")
        if isinstance(data, Mapping):
            top_maps.append(data)
    for mapping in [*top_maps, *walk_maps(root)]:
        if not actual:
            actual = _pick_actual(mapping)
        if not status:
            status = str(mapping.get("dateStatus") or mapping.get("date_status") or "").strip()
        if not snapshot:
            snap = mapping.get("snapshotTime") or mapping.get("snapshot_time")
            if snap:
                snapshot = str(snap).strip()
        _pick_freshness_flags(mapping)
        if actual and status and snapshot and is_realtime is not None:
            break

    req = normalize_trade_date(requested)
    warns = " ".join(quality_warnings(payload, "x")).lower()
    stale = False
    notes: list[str] = []
    if status.lower() == "mismatch" or "date_mismatch" in warns:
        stale = True
        notes.append("日期错位")
    if req and actual and actual != req:
        if actual < req:
            stale = True
            notes.append("非当日")
        elif actual > req:
            notes.append("数据日新于请求日")
    if is_realtime is False and not stale:
        # 同日但非实时：仍可用，须标快照；不按昨收空仓
        notes.append("非实时快照")
    return {
        "actual_trade_date": actual,
        "date_status": status,
        "snapshot_time": snapshot,
        "stale": stale,
        "is_realtime": is_realtime,
        "notes": notes,
    }


def merge_freshness(
    *parts: dict[str, Any],
    requested: str = "",
) -> dict[str, Any]:
    """合并多工具时效：任一 stale 则整体 stale；快照时刻取最新。"""
    actuals = [str(p.get("actual_trade_date") or "") for p in parts if p.get("actual_trade_date")]
    snaps = [str(p.get("snapshot_time") or "") for p in parts if p.get("snapshot_time")]
    notes: list[str] = []
    stale = False
    realtime_flags = [
        p.get("is_realtime") for p in parts if p.get("is_realtime") is not None
    ]
    for part in parts:
        stale = stale or bool(part.get("stale"))
        for note in part.get("notes") or []:
            text = str(note).strip()
            if text and text not in notes:
                notes.append(text)
    actual = min(actuals) if actuals else normalize_trade_date(requested)
    is_realtime: bool | None
    if not realtime_flags:
        is_realtime = None
    else:
        is_realtime = all(bool(flag) for flag in realtime_flags)
        if is_realtime is False and "非实时快照" not in notes and not stale:
            notes.append("非实时快照")
    return {
        "actual_trade_date": actual,
        "requested_trade_date": normalize_trade_date(requested),
        "snapshot_time": max(snaps) if snaps else "",
        "stale": stale,
        "is_realtime": is_realtime,
        "notes": notes,
    }


def tool_failed(payload: Any) -> bool:
    return bool(isinstance(payload, Mapping) and payload.get("is_error"))


__all__ = [
    "ALIASES",
    "LADDER_INHERIT_KEYS",
    "clean_code",
    "extract_freshness",
    "field",
    "max_metric",
    "merge_freshness",
    "metric",
    "normal_key",
    "normalize_trade_date",
    "number",
    "quality_warnings",
    "row_count",
    "rows_by_code",
    "structured",
    "text_field",
    "tool_failed",
    "walk_maps",
]
