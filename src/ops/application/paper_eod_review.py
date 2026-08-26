"""日终五交易日回看复盘包：买过/没买/没卖 + 完整日 K + 环境量能板块。

数字只来自本地 market 仓（及可选资金流路由）；缺数标明 not_observed，禁止编造。
"""
from __future__ import annotations

from collections.abc import Iterable
import logging
import math
import sqlite3
from typing import Any

from src.ops.application.paper_copy_zh import format_lookback_for_prompt
from src.ops.application.paper_decided_by import count_fills_by_decided_by
from src.ops.application.paper_exec import BUY_ACTIONS, SELL_ACTIONS

logger = logging.getLogger(__name__)

from src.ops.application.paper_eod_bars import (
    _PANEL_BAR_FIELDS,
    _bars_from_history,
    _bars_from_panel,
    _lookback_panels,
    _pct,
    _safe_float,
)

LOOKBACK_TRADING_DAYS = 5


def resolve_lookback_days(market: Any, trade_date: str, *, n: int = LOOKBACK_TRADING_DAYS) -> list[str]:
    """含 trade_date（若在日历中）往前共 n 个交易日。"""
    days = list(market.trading_days(end=trade_date) or [])
    if not days:
        # 无日历时退化为自然日切片，调用方应知质量较弱
        return [trade_date]
    if trade_date in days:
        idx = days.index(trade_date)
    else:
        # 取 ≤ trade_date 的最后一天
        idx = len(days) - 1
        while idx >= 0 and days[idx] > trade_date:
            idx -= 1
        if idx < 0:
            return days[-n:] if days else [trade_date]
    start = max(0, idx - n + 1)
    return days[start : idx + 1]




_ATTENTION_FLAGS = frozenset({"planned", "ordered", "auction"})


def _collect_universe(
    ops: Any,
    *,
    slug: str,
    cabin_id: str,
    lookback_days: list[str],
) -> dict[str, dict[str, Any]]:
    """合并持仓 / 成交 / 拒单 / 预案 / 盯盘涉及的标的。

    额外记录 first_attention：最早进入预案/盯盘/竞价关注的交易日。
    「错过」只能从该日起算，禁止把入池前涨幅算成踏空。
    """
    names: dict[str, dict[str, Any]] = {}

    def touch(code: str, **extra: Any) -> None:
        code = str(code or "").strip()
        if not code:
            return
        row = names.setdefault(
            code,
            {"code": code, "name": code, "flags": set(), "first_attention": None},
        )
        if extra.get("name"):
            row["name"] = extra["name"]
        flags = list(extra.get("flags") or [])
        for flag in flags:
            row["flags"].add(flag)
        on_date = str(extra.get("on_date") or "").strip()
        if on_date and _ATTENTION_FLAGS.intersection(flags):
            prev = row.get("first_attention")
            if prev is None or on_date < str(prev):
                row["first_attention"] = on_date

    for pos in ops.list_paper_positions(cabin_id):
        touch(pos.get("code"), name=pos.get("name"), flags=["held"])

    fills = ops.list_paper_fills(cabin_id, limit=200)
    for fill in fills:
        day = str(fill.get("created_at") or "")[:10]
        if lookback_days and day and day < lookback_days[0]:
            continue
        if lookback_days and day and day > lookback_days[-1]:
            continue
        action = str(fill.get("action") or "")
        flags = ["traded"]
        if action in {"open", "add", "buy_dip"}:
            flags.append("bought")
        if action in {"reduce", "close", "take_profit", "stop_cut", "trim_high"}:
            flags.append("sold")
        touch(fill.get("code"), name=fill.get("name"), flags=flags, on_date=day)
        names[str(fill.get("code"))]["fills"] = names[str(fill.get("code"))].get("fills") or []
        names[str(fill.get("code"))]["fills"].append(fill)

    for day in lookback_days:
        plan = ops.get_nextday_plan(slug, day)
        if not plan:
            continue
        for item in plan.get("items") or []:
            if not isinstance(item, dict):
                continue
            touch(
                item.get("code"),
                name=item.get("name"),
                flags=["planned"],
                on_date=day,
            )

    for run in ops.list_monitor_runs(slug, limit=80):
        started = str(run.get("started_at") or "")[:10]
        if lookback_days and started and (started < lookback_days[0] or started > lookback_days[-1]):
            continue
        for reject in run.get("rejects") or []:
            touch(reject.get("code"), flags=["rejected"], on_date=started)
        for order in run.get("orders") or []:
            if isinstance(order, dict):
                touch(order.get("code"), flags=["ordered"], on_date=started)
        snap = run.get("snapshot") if isinstance(run.get("snapshot"), dict) else {}
        for stance in snap.get("auction_stances") or []:
            if isinstance(stance, dict):
                touch(stance.get("code"), flags=["auction"], on_date=started)

    return names


def _instruments_meta(market: Any, codes: Iterable[str]) -> dict[str, dict[str, str]]:
    """批量取标的名称/板块/行业。

    经 ``MarketStore.instruments_meta`` 而不是直连 ``market.conn``：跨上下文只走
    公开 API，且一次查完——此前是在复盘循环里逐票各打一次查询。
    """
    try:
        return market.instruments_meta(codes)
    except (AttributeError, OSError, sqlite3.Error):
        return {}


def _trade_return_pct(
    fills: list[dict[str, Any]], last_close: float | None
) -> float | None:
    """这笔操作到目前为止的盈亏：自买入均价起，卖出的按成交价、还持有的按窗末盯市。

    标的整窗涨跌**不是**你这笔的盈亏。窗口前半段的下跌发生在你买入之前，把它记在
    今天才建仓的头上，就会得出「买入后走弱、检查止损」这种与事实相反的结论。

    只在窗口内有买入时才给数；纯卖出（窗口前建的仓）无从算起，返回 ``None``。
    超卖部分按买入层数封顶，不让窗前老仓的平仓污染这笔的口径。
    """
    buy_layers = 0.0
    buy_value = 0.0
    sell_layers = 0.0
    sell_value = 0.0
    for fill in fills:
        action = str(fill.get("action") or "")
        layers = _safe_float(fill.get("layers")) or 0.0
        price = _safe_float(fill.get("mark_price"))
        if layers <= 0 or price is None or price <= 0:
            continue
        if action in BUY_ACTIONS:
            buy_layers += layers
            buy_value += price * layers
        elif action in SELL_ACTIONS:
            sell_layers += layers
            sell_value += price * layers
    if buy_layers <= 0 or buy_value <= 0:
        return None
    matched = min(sell_layers, buy_layers)
    exit_value = (sell_value / sell_layers) * matched if sell_layers > 0 else 0.0
    open_layers = buy_layers - matched
    if open_layers > 1e-9:
        if last_close is None or last_close <= 0:
            return None
        exit_value += last_close * open_layers
    return round((exit_value / buy_value - 1.0) * 100.0, 3)


def _last_sell_day(fills: list[dict[str, Any]]) -> str | None:
    days = [
        str(fill.get("created_at") or "")[:10]
        for fill in fills
        if str(fill.get("action") or "") in SELL_ACTIONS
    ]
    days = [day for day in days if day]
    return max(days) if days else None


def _return_since(bars: list[dict[str, Any]], since_date: str | None) -> float | None:
    """自 since_date（含）起至窗末的收益；无 since 则退回整窗。"""
    if not bars:
        return None
    if not since_date:
        return _pct(bars[0].get("close"), bars[-1].get("close"))
    scoped = [b for b in bars if str(b.get("trade_date") or "") >= since_date]
    if not scoped:
        return None
    return _pct(scoped[0].get("close"), scoped[-1].get("close"))


def _classify_status(
    flags: set[str],
    *,
    trade_date: str,
    first_attention: str | None,
) -> str:
    if "bought" in flags and "sold" in flags:
        return "bought_and_sold"
    if "bought" in flags:
        return "bought"
    if "sold" in flags:
        return "sold"
    if "held" in flags:
        return "held"
    if flags & _ATTENTION_FLAGS:
        # 今日才进预案/盯盘：只能算新入池，不能把入池前涨幅算「错过」
        if not first_attention or first_attention >= trade_date:
            return "new_pick"
        return "missed"
    if "rejected" in flags:
        return "rejected"
    return "watched"


def build_environment(
    *,
    lookback_days: list[str],
    name_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """基于回看包内 K 线聚合环境：量能、涨跌家数、板块。不编造大盘指数。"""
    by_day: list[dict[str, Any]] = []
    for day in lookback_days:
        amounts: list[float] = []
        volumes: list[float] = []
        pcts: list[float] = []
        for row in name_rows:
            for bar in row.get("bars") or []:
                if bar.get("trade_date") != day:
                    continue
                if bar.get("amount") is not None:
                    amounts.append(float(bar["amount"]))
                if bar.get("volume") is not None:
                    volumes.append(float(bar["volume"]))
                if bar.get("pct") is not None:
                    pcts.append(float(bar["pct"]))
        by_day.append(
            {
                "trade_date": day,
                "universe_amount": round(sum(amounts), 2) if amounts else None,
                "universe_volume": round(sum(volumes), 2) if volumes else None,
                "avg_pct": round(sum(pcts) / len(pcts), 3) if pcts else None,
                "up": sum(1 for p in pcts if p > 0),
                "down": sum(1 for p in pcts if p < 0),
                "flat": sum(1 for p in pcts if p == 0),
                "sample": len(pcts),
            }
        )

    board_map: dict[str, list[float]] = {}
    for row in name_rows:
        board = str(row.get("board") or row.get("industry") or "未分类")
        bars = row.get("bars") or []
        if not bars:
            continue
        last_pct = bars[-1].get("pct")
        if last_pct is None:
            continue
        board_map.setdefault(board, []).append(float(last_pct))
    boards = [
        {
            "board": board,
            "n": len(vals),
            "avg_pct_last": round(sum(vals) / len(vals), 3),
        }
        for board, vals in sorted(board_map.items(), key=lambda x: -len(x[1]))
    ][:12]

    return {
        "scope": "paper_universe",
        "note": "环境统计仅覆盖本战法回看池，非全市场；大盘指数/全市场资金若未观测则不写",
        "by_day": by_day,
        "boards": boards,
    }


def maybe_fetch_capital_flow(codes: list[str], *, limit: int = 5) -> list[dict[str, Any]]:
    """可选资金流：失败则 not_observed，不阻断日终。"""
    out: list[dict[str, Any]] = []
    try:
        from src.market import fetch_capital_flow_routed
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"capital_flow_unavailable: {exc}"}]
    for code in codes[:limit]:
        try:
            frame = fetch_capital_flow_routed(code)
            if frame is None or getattr(frame, "empty", True):
                out.append({"code": code, "status": "not_observed", "rows": []})
                continue
            # 只取最近若干行摘要
            rows = []
            for row in frame.tail(5).itertuples(index=False):
                item = {}
                for col in frame.columns:
                    val = getattr(row, col, None)
                    if isinstance(val, float) and math.isnan(val):
                        val = None
                    item[str(col)] = val
                rows.append(item)
            out.append({"code": code, "status": "ok", "rows": rows})
        except Exception as exc:  # noqa: BLE001
            out.append({"code": code, "status": "not_observed", "error": str(exc)[:200]})
    return out


def build_eod_lookback_pack(
    ops: Any,
    market: Any,
    *,
    slug: str,
    trade_date: str,
    lookback: int = LOOKBACK_TRADING_DAYS,
    include_capital_flow: bool = False,
) -> dict[str, Any]:
    cabin = ops.ensure_paper_cabin(slug)
    days = resolve_lookback_days(market, trade_date, n=lookback)
    start = days[0] if days else trade_date
    end = days[-1] if days else trade_date
    universe = _collect_universe(ops, slug=slug, cabin_id=cabin["id"], lookback_days=days)

    name_rows: list[dict[str, Any]] = []
    instruments = _instruments_meta(market, universe.keys())
    # 为什么批量：回看池 N 只票原来就是 N 次 history（持仓+成交+拒单+预案+盯盘
    # 合并后常见上百只，极端下两千只候选就是两千次 SQLite 往返）；
    # 面板一次 IN (...) 取回整个窗口，再在内存按票切列。
    panels = _lookback_panels(market, sorted(universe), start=start, end=end)
    for code, meta in sorted(universe.items()):
        inst = instruments.get(code, {})
        flags: set[str] = set(meta.get("flags") or set())
        first_attention = str(meta.get("first_attention") or "") or None
        if panels is not None:
            bars = _bars_from_panel(panels, code)
        else:
            # 注入的行情对象没有 load_panel（旧 fake / 精简实现）才逐票回退
            try:
                frame = market.history(code, start=start, end=end, adjust="qfq")
                bars = _bars_from_history(frame)
            except Exception as exc:  # noqa: BLE001
                logger.warning("eod lookback history failed %s: %s", code, exc)
                bars = []
        first = bars[0]["close"] if bars else None
        last = bars[-1]["close"] if bars else None
        status = _classify_status(
            flags, trade_date=trade_date, first_attention=first_attention
        )
        row_fills = meta.get("fills") or []
        name_rows.append(
            {
                "code": code,
                "name": inst.get("name") or meta.get("name") or code,
                "board": inst.get("board") or "",
                "industry": inst.get("industry") or "",
                "status": status,
                "flags": sorted(flags),
                "first_attention": first_attention,
                "fills": row_fills,
                "bars": bars,
                "bars_count": len(bars),
                "window_return_pct": _pct(first, last),
                "since_attention_return_pct": _return_since(bars, first_attention),
                # 买过/卖过要按自己的成交价说话，别拿标的整窗涨跌顶包
                "trade_return_pct": _trade_return_pct(row_fills, last),
                "post_exit_return_pct": _return_since(bars, _last_sell_day(row_fills)),
                "quality": "ok" if bars else "kline_missing",
            }
        )

    environment = build_environment(lookback_days=days, name_rows=name_rows)
    capital: list[dict[str, Any]] = []
    if include_capital_flow:
        # 优先对买过/错过的票取资金流
        prefer = [
            r["code"]
            for r in name_rows
            if r["status"] in {"bought", "missed", "bought_and_sold", "held"}
        ]
        capital = maybe_fetch_capital_flow(prefer or [r["code"] for r in name_rows])

    missed = [r for r in name_rows if r["status"] == "missed"]
    new_picks = [r for r in name_rows if r["status"] == "new_pick"]
    bought = [r for r in name_rows if r["status"] in {"bought", "bought_and_sold"}]
    sold = [r for r in name_rows if r["status"] in {"sold", "bought_and_sold"}]
    pack_fills: list[dict[str, Any]] = []
    for row in name_rows:
        pack_fills.extend(row.get("fills") or [])

    return {
        "slug": slug,
        "trade_date": trade_date,
        "lookback_trading_days": days,
        "lookback_n": len(days),
        "universe_size": len(name_rows),
        "fills_by_decided_by": count_fills_by_decided_by(pack_fills),
        "bought": [
            {
                "code": r["code"],
                "name": r["name"],
                "trade_return_pct": r["trade_return_pct"],
                "window_return_pct": r["window_return_pct"],
            }
            for r in bought
        ],
        "missed": [
            {
                "code": r["code"],
                "name": r["name"],
                "window_return_pct": r["window_return_pct"],
                "since_attention_return_pct": r["since_attention_return_pct"],
                "first_attention": r["first_attention"],
                "board": r["board"],
            }
            for r in missed
        ],
        "new_picks": [
            {
                "code": r["code"],
                "name": r["name"],
                "window_return_pct": r["window_return_pct"],
                "first_attention": r["first_attention"],
                "board": r["board"],
            }
            for r in new_picks
        ],
        "sold": [
            {
                "code": r["code"],
                "name": r["name"],
                "trade_return_pct": r["trade_return_pct"],
                "post_exit_return_pct": r["post_exit_return_pct"],
                "window_return_pct": r["window_return_pct"],
            }
            for r in sold
        ],
        "environment": environment,
        "capital_flow": capital,
        "names": name_rows,
    }



def extract_miss_lessons_from_pack(
    *,
    slug: str,
    trade_date: str,
    pack: dict[str, Any],
) -> list[dict[str, Any]]:
    """从五日内买/没买/没卖提炼可吸入教训。

    每条教训都要用**与该结论对应的口径**，否则会给出与事实相反的建议：

    - 错过：``since_attention_return_pct``（自入池日起），别用整窗收益冤枉新票。
    - 买入后走弱：``trade_return_pct``（自买入均价起）。拿标的整窗跌幅当依据，会把
      「买入前跌过」说成「买入后走弱」，还叫人去查止损。
    - 卖出后仍强：``post_exit_return_pct``（自卖出日起）。整窗上涨可能全发生在买入前。
    """
    lessons: list[dict[str, Any]] = []
    for row in pack.get("names") or []:
        status = row.get("status")
        ret = row.get("window_return_pct")
        since_ret = row.get("since_attention_return_pct")
        trade_ret = row.get("trade_return_pct")
        post_ret = row.get("post_exit_return_pct")
        code = row.get("code")
        name = row.get("name")
        first_att = row.get("first_attention")
        if status == "missed" and since_ret is not None and since_ret >= 5.0:
            lessons.append(
                {
                    "slug": slug,
                    "trade_date": trade_date,
                    "kind": "miss",
                    "title": f"错过 {name} {code}",
                    "content": (
                        f"自入池日 {first_att} 起收益 {since_ret}% 且未买入"
                        f"（整窗参考 {ret}%）；复盘竞价/情景是否过严或执行犹豫"
                    ),
                    "evidence": {
                        "code": code,
                        "first_attention": first_att,
                        "since_attention_return_pct": since_ret,
                        "window_return_pct": ret,
                        "bars_count": row.get("bars_count"),
                    },
                }
            )
        if status == "missed" and since_ret is not None and since_ret <= -5.0:
            lessons.append(
                {
                    "slug": slug,
                    "trade_date": trade_date,
                    "kind": "win",
                    "title": f"回避下跌 {name} {code}",
                    "content": (
                        f"入池后未买，自 {first_att} 起收益 {since_ret}%——"
                        "纪律可能正确，记清当时否决理由"
                    ),
                    "evidence": {
                        "code": code,
                        "first_attention": first_att,
                        "since_attention_return_pct": since_ret,
                        "window_return_pct": ret,
                    },
                }
            )
        if (
            status in {"bought", "bought_and_sold"}
            and trade_ret is not None
            and trade_ret <= -5.0
        ):
            lessons.append(
                {
                    "slug": slug,
                    "trade_date": trade_date,
                    "kind": "mistake",
                    "title": f"买入后走弱 {name} {code}",
                    "content": (
                        f"自买入均价起 {trade_ret}%（标的整窗 {ret}%）；"
                        "检视开仓情景与止损是否拖延"
                    ),
                    "evidence": {
                        "code": code,
                        "trade_return_pct": trade_ret,
                        "window_return_pct": ret,
                        "fills": row.get("fills") or [],
                    },
                }
            )
        if (
            status in {"sold", "bought_and_sold"}
            and post_ret is not None
            and post_ret >= 5.0
        ):
            lessons.append(
                {
                    "slug": slug,
                    "trade_date": trade_date,
                    "kind": "revise",
                    "title": f"卖出后仍强 {name} {code}",
                    "content": f"卖出后标的又涨 {post_ret}%；复盘是否过早止盈/减仓",
                    "evidence": {
                        "code": code,
                        "post_exit_return_pct": post_ret,
                        "trade_return_pct": trade_ret,
                        "window_return_pct": ret,
                    },
                }
            )
    # 环境：池内末日普跌仍追高等
    by_day = (pack.get("environment") or {}).get("by_day") or []
    if by_day:
        last = by_day[-1]
        if last.get("avg_pct") is not None and last["avg_pct"] <= -2 and pack.get("bought"):
            lessons.append(
                {
                    "slug": slug,
                    "trade_date": trade_date,
                    "kind": "note",
                    "title": "弱环境仍有买入",
                    "content": (
                        f"回看末日池内均涨跌 {last['avg_pct']}% 且有买入；"
                        "对照板块/量能是否逆势"
                    ),
                    "evidence": {"environment_last": last},
                }
            )
    return lessons
