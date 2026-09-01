"""preset → 代码清单：大屏订阅的唯一入口。

**铁律：纯读路径。** 只解析代码与排序，不写 ``market.db``、不落盘、
不调 ``apply_today_spot``。

三类 preset：

- ``index``：静态指数篮子（在 ``infrastructure/live_tape.py:19 DEFAULT_INDICES``
  的四条之上补北证 50 / 沪深 300 / 中证 500 / 中证 1000 / 上证 50），
  ``instrument_type=INDEX``——指数不在东财 spot 表里，只能走 sina/tencent；
- ``gainers`` / ``losers`` / ``turnover`` / ``amount``：东财全市场截面排序取 Top N。
  截面表本身就是报价（一次 HTTP ~5500 行 23 列，适配器侧 4s TTL），所以解析完
  **直接把行带回去**，全链只取一次数，不再对 Top N 补一次 spot_batch；
- ``watchlist``：显式 codes。

硬上限 ``MAX_PRESET_CODES = 400``：对齐新浪 hq 单批 400 只。再多会被拆成多次
HTTP，而 ``(spot_batch, 来源)`` 的在途名额默认只有 1
（``infrastructure/adapters/router_live.py:25 DEFAULT_ADAPTER_CONCURRENCY``），
排队会把大屏一个 tick 的时间预算整个吃光。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Callable

#: 单个 preset 允许订阅的最大标的数；对齐新浪 hq 单批上限。
MAX_PRESET_CODES = 400
#: 排行榜 preset 的默认 Top N。
DEFAULT_TOP_N = 50

PRESET_INDEX = "index"
PRESET_ALL = "all"
PRESET_SIGNALS = "signals"
PRESET_WATCHLIST = "watchlist"
#: 指数篮子：(代码, 简称)。
INDEX_BASKET: tuple[tuple[str, str], ...] = (
    ("000001", "上证"), ("399001", "深证"), ("399006", "创业"),
    ("000688", "科创"), ("899050", "北证50"), ("000300", "沪深300"),
    ("000905", "中证500"), ("000852", "中证1000"), ("000016", "上证50"),
)

#: 排行榜 preset → (排序字段, 中文名, 是否降序)
RANKED_PRESETS: dict[str, tuple[str, str, bool]] = {
    "gainers": ("pct", "涨幅榜", True),
    "losers": ("pct", "跌幅榜", False),
    "turnover": ("turnover", "换手榜", True),
    "amount": ("amount", "成交额榜", True),
}

ALL_PRESETS: tuple[str, ...] = (PRESET_INDEX, PRESET_ALL, PRESET_SIGNALS, *RANKED_PRESETS, PRESET_WATCHLIST)

CrossSectionFetcher = Callable[[], list[dict[str, Any]]]


class WatchlistError(ValueError):
    """preset 不认识 / 显式 codes 全非法。"""


@dataclass(frozen=True)
class Resolution:
    """一次 preset 解析结果。
    
    ``rows`` 非空表示解析顺带已经拿到了报价（排行榜路径），调用方**不要**
    再对 ``codes`` 发一次 spot_batch。
    """
    
    preset: str
    kind: str  # "static" | "ranked" | "explicit"
    codes: list[str]
    source: str
    instrument_types: dict[str, str] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: 需要另外补一次取数的指数代码。指数**不在东财截面表里**（只能走 sina/tencent），
    #: 而大屏的指数带要跟着推流跳；调用方拿到非空就单独取一次，失败不算整轮失败。
    index_codes: list[str] = field(default_factory=list)
    truncated: bool = False


def list_watchlist_presets() -> list[dict[str, Any]]:
    """给前端下拉用的 preset 目录。"""
    items = [
        {"id": PRESET_INDEX, "label": "指数", "kind": "static", "size": len(INDEX_BASKET)},
        {"id": PRESET_ALL, "label": "全市场", "kind": "ranked", "size": MAX_PRESET_CODES},
        {"id": PRESET_SIGNALS, "label": "信号池", "kind": "ranked", "size": MAX_PRESET_CODES},
        {"id": PRESET_WATCHLIST, "label": "自选", "kind": "explicit", "size": 0},
    ]
    for name, (_key, label, _desc) in RANKED_PRESETS.items():
        items.append({"id": name, "label": label, "kind": "ranked", "size": DEFAULT_TOP_N})
    return items


def _clean_codes(codes: list[str] | None) -> list[str]:
    """去空白 / 去重 / 归一；非法代码静默丢弃（大屏不该因一个错码整条流挂掉）。"""
    from src.market.infrastructure.store import MarketError, normalize_code
    
    out: list[str] = []
    seen: set[str] = set()
    for raw in codes or []:
        text = str(raw).strip()
        if not text:
            continue
        try:
            code = normalize_code(text)
        except MarketError:
            continue
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _num(value: Any) -> float:
    """NaN / inf / 非数一律回 0：它们既过不了 JSON，也会污染排序。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def default_cross_section() -> list[dict[str, Any]]:
    """东财全市场截面 → 报价行。
    
    这里够到了 ``EastmoneyAdapter`` 的两个受保护成员，理由写清楚：公开的
    ``fetch_live_quotes`` 必须先给一份代码清单，而且只吐固定 11 个字段，把排行榜
    要的**换手率 / 量比 / 涨速**丢掉了——那三列就在同一张已经下载好的表里，
    为它们再发一次 HTTP 是纯浪费。``_load_spot_raw`` 自带 4s TTL，与本模块
    6s 的截面周期天然对齐。
    """
    from src.market.infrastructure.adapters import get_adapter
    
    adapter = get_adapter("eastmoney")
    raw = adapter._load_spot_raw(who="全市场截面")  # noqa: SLF001 - 见 docstring
    return rows_from_spot_frame(adapter._normalize_spot(raw, include_rich=True))


def rows_from_spot_frame(frame: Any) -> list[dict[str, Any]]:
    """归一后的东财截面表 → 统一报价行（含 turnover / volume_ratio / speed）。"""
    rows: list[dict[str, Any]] = []
    for item in frame.to_dict(orient="records"):
        code = str(item.get("code") or "").strip().zfill(6)
        price = _num(item.get("close"))
        if not code or price <= 0:
            continue  # 停牌行最新价是 NaN，带出去就是非法 JSON
        row = {k: _num(item.get(k)) for k in ("open", "high", "low", "change", "pct", "volume", "amount")}
        row.update({k: _num(item.get(cn)) for k, cn in (("turnover", "换手率"), ("volume_ratio", "量比"), ("speed", "涨速"))})
        row.update(
            {
                "code": code,
                "name": str(item.get("name") or ""),
                "price": price,
                "prev_close": _num(item.get("prev_close")) or price,
                "trade_time": "",
                "source": "eastmoney",
            }
        )
        for key in ("open", "high", "low"):
            row[key] = row[key] or price
        rows.append(row)
    return rows


#: 「今天真的在动」的宇宙怎么切：(排序字段, 是否降序, 取多少只)。顺序即优先级。
#: 四条切片正好对应大屏上的四个榜，于是「信号里出现的票」与「屏幕上看到的票」
#: 是同一批，可解释性最强。
UNIVERSE_SLICES: tuple[tuple[str, bool, int], ...] = (
    ("pct", True, 120),      # 涨幅头部：临近涨停 / 快速拉升 / 炸板都出在这里
    ("pct", False, 80),      # 跌幅头部
    ("amount", True, 120),   # 成交额头部：大票的放量突破
    ("turnover", True, 80),  # 换手头部：小票异动
)


def movers_universe(
    rows: list[dict[str, Any]],
    *,
    limit: int = MAX_PRESET_CODES,
    slices: tuple[tuple[str, bool, int], ...] = UNIVERSE_SLICES,
) -> list[dict[str, Any]]:
    """从全市场截面里挑出「今天真的在动」的那批，去重后截到 ``limit``。

    **为什么不能直接 ``rows[:400]``**（这就是「盯盘大屏一整天零信号」的根因）：
    ``ak.stock_zh_a_spot_em()`` 按**代码倒序**返回（``fid=f12`` + ``po=1``），
    截面表头部清一色是 920xxx / 8xxxxx 的北交所票。于是信号引擎与大屏整天盯着
    一批与用户无关的标的跑规则——涨停就在屏幕上，信号栏却永远是「无信号」。

    只排序不取数：入参就是已经下载好的那张表，这里一次 HTTP 都不发。
    """
    picked: dict[str, dict[str, Any]] = {}
    for key, descending, count in slices:
        if len(picked) >= limit:
            break
        ordered = sorted(rows, key=lambda row: _num(row.get(key)), reverse=descending)
        for row in ordered[: max(0, int(count))]:
            code = str(row.get("code") or "")
            if code and code not in picked:
                picked[code] = row
    # 四条榜互有重叠，取完常常填不满上限；余量按 |涨跌幅| 补齐——把 400 只的
    # 额度用足，「临近涨停」这类规则才有足够的候选。
    if len(picked) < limit:
        hottest = sorted(rows, key=lambda row: abs(_num(row.get("pct"))), reverse=True)
        for row in hottest:
            code = str(row.get("code") or "")
            if code and code not in picked:
                picked[code] = row
            if len(picked) >= limit:
                break
    return list(picked.values())[:limit]


def resolve_preset(
    preset: str,
    codes: list[str] | None = None,
    *,
    top_n: int = DEFAULT_TOP_N,
    cross_section: CrossSectionFetcher | None = None,
) -> Resolution:
    """解析 preset。硬上限 ``MAX_PRESET_CODES`` 在**每条分支**上都生效。"""
    name = str(preset or "").strip().lower() or PRESET_INDEX
    limit = min(max(1, int(top_n)), MAX_PRESET_CODES)
    
    if name == PRESET_INDEX:
        basket = [code for code, _label in INDEX_BASKET][:MAX_PRESET_CODES]
        return Resolution(
            preset=name, kind="static", codes=basket, source="static_index",
            instrument_types={code: "INDEX" for code in basket},
            truncated=len(INDEX_BASKET) > MAX_PRESET_CODES,
        )
    if name == PRESET_ALL:
        # 大屏的行情流：**四榜合集 + 指数**。取整表前 400 行是错的，见 movers_universe。
        rows = list((cross_section or default_cross_section)() or [])
        wanted = set(_clean_codes(codes)) if codes else set()
        if wanted:
            rows = [row for row in rows if str(row.get("code") or "") in wanted]
        picked = movers_universe(rows)
        basket_codes = [code for code, _label in INDEX_BASKET]
        inst_types = {code: "INDEX" for code in basket_codes}
        inst_types.update({str(row.get("code") or ""): "STOCK" for row in picked})
        return Resolution(
            preset=name, kind="ranked", source="eastmoney_spot_all", rows=picked,
            codes=[str(row.get("code") or "") for row in picked],
            instrument_types=inst_types,
            # 指数不在东财截面里：交给调用方单独补一次，指数带才会跟着推流跳。
            index_codes=basket_codes,
            truncated=len(rows) > len(picked),
        )

    if name == PRESET_SIGNALS:
        # 信号池：同一套四榜合集，但**不含指数**——「临近涨停」放在指数上没有意义。
        rows = list((cross_section or default_cross_section)() or [])
        picked = movers_universe(rows)
        return Resolution(
            preset=name, kind="ranked", source="eastmoney_signals", rows=picked,
            codes=[str(row.get("code") or "") for row in picked],
            instrument_types={str(row.get("code") or ""): "STOCK" for row in picked},
            truncated=len(rows) > len(picked),
        )

    if name == PRESET_WATCHLIST:
        clean = _clean_codes(codes)
        if not clean:
            raise WatchlistError("watchlist 预设必须给至少一个合法代码")
        capped = clean[:MAX_PRESET_CODES]
        return Resolution(
            preset=name, kind="explicit", codes=capped, source="explicit",
            instrument_types={code: "STOCK" for code in capped},
            truncated=len(clean) > MAX_PRESET_CODES,
        )
    
    spec = RANKED_PRESETS.get(name)
    if spec is None:
        raise WatchlistError(f"未知 preset：{preset!r}（可选 {', '.join(ALL_PRESETS)}）")
    key, _label, descending = spec
    rows = list((cross_section or default_cross_section)() or [])
    wanted = set(_clean_codes(codes)) if codes else set()
    if wanted:
        rows = [row for row in rows if str(row.get("code") or "") in wanted]
    ordered = sorted(rows, key=lambda row: _num(row.get(key)), reverse=descending)
    picked = ordered[:limit][:MAX_PRESET_CODES]
    return Resolution(
        preset=name, kind="ranked", source="eastmoney_spot", rows=picked,
        codes=[str(row.get("code") or "") for row in picked],
        instrument_types={str(row.get("code") or ""): "STOCK" for row in picked},
        truncated=len(rows) > len(picked),
    )


__all__ = [
    "ALL_PRESETS", "DEFAULT_TOP_N", "INDEX_BASKET", "MAX_PRESET_CODES",
    "PRESET_INDEX", "PRESET_ALL", "PRESET_SIGNALS", "PRESET_WATCHLIST",
    "RANKED_PRESETS", "Resolution", "UNIVERSE_SLICES", "WatchlistError",
    "default_cross_section", "movers_universe",
    "list_watchlist_presets", "resolve_preset", "rows_from_spot_frame",
]
