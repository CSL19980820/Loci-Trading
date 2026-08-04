"""换手率 / 流通股本修补。

当日 spot 不含换手率，只能用「严格早于当日」的最近流通股本估算。
若误用 coverage.last_date（可能已是今天），会整日写空并雪崩到后续交易日。
本模块提供 as-of 股本查询与缺换手回填，供 sync / 体检修复共用。

东财历史成交量为「手」、新浪/腾讯 spot 为「股」。用 ``volume/turnover`` 反推股本时
若未统一单位，股本会小 100 倍，spot 换手率可膨胀到上千百分数。反推优先用
``amount / (close * turnover)``（成交额为元，与量单位无关）。
"""
from __future__ import annotations

from typing import Any, Sequence

from src.market.infrastructure.store import MarketStore

#: 倒序回看交易日上限；超过仍无股本则放弃该标的。
_ASOF_LOOKBACK_DAYS = 60
#: 单日股本覆盖达到此数量即认为足够密，可提前结束回看。
_ASOF_DENSE_CODES = 4000
#: 换手率（小数）超过此值视为脏数据，修复时清空重算。
_INSANE_TURNOVER = 1.0
#: amount/(volume*close) 落在此区间 → 成交量仍是「手」。
_LOT_RATIO_LO = 50.0
_LOT_RATIO_HI = 150.0


def _infer_shares(volume: float, turnover: float, *, amount: float | None, close: float | None) -> float | None:
    """由换手率反推流通股本（股）。

    优先 ``amount/(close*turnover)``，避免东财「手」与新浪「股」混用。
    """
    if turnover <= 0:
        return None
    if amount is not None and close is not None and amount > 0 and close > 0:
        shares = amount / (close * turnover)
        if shares > 0:
            return shares
    if volume <= 0:
        return None
    # 回退：若量看起来仍是手（amount/(vol*close)≈100），先还原成股再除。
    if amount is not None and close is not None and close > 0 and volume > 0:
        ratio = amount / (volume * close)
        if _LOT_RATIO_LO <= ratio <= _LOT_RATIO_HI:
            volume = volume * 100.0
    shares = volume / turnover
    return shares if shares > 0 else None


def load_shares_asof(store: MarketStore, before_date: str) -> dict[str, float]:
    """每只标的在 ``before_date`` 之前最近一次有效流通股本。

    按交易日历（或 quotes 去重日）倒序点查，跳过中间空股本日。
    避免对全表做 ``MAX(trade_date) GROUP BY code``（千万行库上过慢）。

    若某票从未落过 ``outstanding_share``（如长期走 tencent/eastmoney），
    但历史有换手率，则用成交额/价/换手反推股本，供 spot 估算。
    """
    before = str(before_date or "").strip()
    if not before:
        return {}

    days = [
        str(row[0])
        for row in store.conn.execute(
            "SELECT trade_date FROM trading_calendar"
            " WHERE trade_date < ? ORDER BY trade_date DESC LIMIT ?",
            (before, _ASOF_LOOKBACK_DAYS),
        )
    ]
    if not days:
        days = [
            str(row[0])
            for row in store.conn.execute(
                "SELECT DISTINCT trade_date FROM quotes_daily"
                " WHERE trade_date < ? ORDER BY trade_date DESC LIMIT ?",
                (before, _ASOF_LOOKBACK_DAYS),
            )
        ]

    out: dict[str, float] = {}
    for trade_date in days:
        rows = store.conn.execute(
            "SELECT code, outstanding_share FROM quotes_daily"
            " WHERE trade_date = ?"
            "   AND outstanding_share IS NOT NULL"
            "   AND outstanding_share > 0",
            (trade_date,),
        )
        for row in rows:
            code = str(row[0])
            if code in out:
                continue
            try:
                shares = float(row[1])
            except (TypeError, ValueError):
                continue
            if shares > 0:
                out[code] = shares
        if len(out) >= _ASOF_DENSE_CODES:
            break

    # 第二轮：用 amount/(close*turnover) 反推仍缺股本的标的（东财有换手无股本）。
    # 必须扫完 lookback：中间空股本日 added=0 不能提前结束。
    for trade_date in days:
        rows = store.conn.execute(
            "SELECT code, volume, turnover, amount, close FROM quotes_daily"
            " WHERE trade_date = ?"
            "   AND turnover IS NOT NULL AND turnover > 0"
            "   AND volume IS NOT NULL AND volume > 0",
            (trade_date,),
        )
        for row in rows:
            code = str(row[0])
            if code in out:
                continue
            try:
                volume = float(row[1])
                turnover = float(row[2])
                amount = float(row[3]) if row[3] is not None else None
                close = float(row[4]) if row[4] is not None else None
            except (TypeError, ValueError):
                continue
            shares = _infer_shares(volume, turnover, amount=amount, close=close)
            if shares is not None:
                out[code] = shares
    return out


def backfill_missing_turnover(
    store: MarketStore,
    *,
    since: str | None = None,
    trade_dates: Sequence[str] | None = None,
) -> dict[str, Any]:
    """用 as-of 流通股本回填缺换手率（及缺失股本）的日 K 行。

    只改 ``outstanding_share`` / ``turnover``，不动 OHLC。
    返回 ``updated`` / ``skipped`` / ``dates_scanned``。
    """
    clauses = [
        "(turnover IS NULL OR turnover <= 0)",
        "volume IS NOT NULL",
        "volume > 0",
    ]
    params: list[Any] = []
    if trade_dates:
        dates = sorted({str(d).strip() for d in trade_dates if str(d).strip()})
    else:
        if since:
            clauses.append("trade_date >= ?")
            params.append(str(since).strip())
        where = " AND ".join(clauses)
        dates = [
            str(row[0])
            for row in store.conn.execute(
                f"SELECT DISTINCT trade_date FROM quotes_daily WHERE {where} ORDER BY trade_date",
                params,
            )
        ]

    updated = 0
    skipped = 0
    need_where = " AND ".join(clauses[:3])  # 不含 since，按日过滤

    for trade_date in dates:
        shares_map = load_shares_asof(store, trade_date)
        rows = store.conn.execute(
            f"""
            SELECT code, volume FROM quotes_daily
            WHERE trade_date = ? AND {need_where}
            """,
            (trade_date,),
        ).fetchall()
        payload: list[tuple[float, float, str, str]] = []
        for code, volume in rows:
            shares = shares_map.get(str(code))
            if shares is None or shares <= 0:
                skipped += 1
                continue
            try:
                vol = float(volume)
            except (TypeError, ValueError):
                skipped += 1
                continue
            if vol <= 0:
                skipped += 1
                continue
            turnover = vol / shares
            # 仍离谱则跳过，避免把手单位股本写回库。
            if turnover > _INSANE_TURNOVER:
                skipped += 1
                continue
            payload.append((shares, turnover, trade_date, str(code)))
        if not payload:
            continue
        with store._transaction() as cursor:
            cursor.executemany(
                """
                UPDATE quotes_daily
                   SET outstanding_share = ?, turnover = ?
                 WHERE trade_date = ? AND code = ?
                """,
                payload,
            )
        updated += len(payload)

    return {
        "updated": updated,
        "skipped": skipped,
        "dates_scanned": len(dates),
    }


def scale_lot_volumes(store: MarketStore, *, since: str) -> dict[str, Any]:
    """把仍按「手」入库的成交量 ×100 成股（用 amount/(vol*close)≈100 判定）。"""
    since_s = str(since).strip()
    rows = store.conn.execute(
        """
        SELECT code, trade_date, volume
          FROM quotes_daily
         WHERE trade_date >= ?
           AND volume IS NOT NULL AND volume > 0
           AND amount IS NOT NULL AND amount > 0
           AND close IS NOT NULL AND close > 0
           AND amount / (volume * close) BETWEEN ? AND ?
        """,
        (since_s, _LOT_RATIO_LO, _LOT_RATIO_HI),
    ).fetchall()
    if not rows:
        return {"scaled": 0, "since": since_s}
    payload = [(float(volume) * 100.0, trade_date, str(code)) for code, trade_date, volume in rows]
    with store._transaction() as cursor:
        cursor.executemany(
            """
            UPDATE quotes_daily
               SET volume = ?
             WHERE trade_date = ? AND code = ?
            """,
            payload,
        )
    return {"scaled": len(payload), "since": since_s}


def repair_inflated_turnover(store: MarketStore, *, since: str) -> dict[str, Any]:
    """清空自 ``since`` 起被单位错位撑爆的换手/股本，再按正确口径回填。

    步骤：
    1. 东财残留「手」成交量 ×100 → 股
    2. 清空 spot 估出的换手/股本，以及 turnover>100% 的脏行
    3. ``backfill_missing_turnover`` 用成交额反推股本重算
    """
    since_s = str(since).strip()
    scaled = scale_lot_volumes(store, since=since_s)

    cleared = store.conn.execute(
        """
        SELECT COUNT(*) FROM quotes_daily
         WHERE trade_date >= ?
           AND (
             source LIKE '%\\_spot' ESCAPE '\\'
             OR (turnover IS NOT NULL AND turnover > ?)
           )
           AND (turnover IS NOT NULL OR outstanding_share IS NOT NULL)
        """,
        (since_s, _INSANE_TURNOVER),
    ).fetchone()[0]

    with store._transaction() as cursor:
        cursor.execute(
            """
            UPDATE quotes_daily
               SET outstanding_share = NULL, turnover = NULL
             WHERE trade_date >= ?
               AND (
                 source LIKE '%\\_spot' ESCAPE '\\'
                 OR (turnover IS NOT NULL AND turnover > ?)
               )
            """,
            (since_s, _INSANE_TURNOVER),
        )

    backfill = backfill_missing_turnover(store, since=since_s)
    return {
        "since": since_s,
        "volumes_scaled": scaled["scaled"],
        "cleared": int(cleared),
        **backfill,
    }
