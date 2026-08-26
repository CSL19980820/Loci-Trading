"""换手率 / 流通股本修补。

当日 spot 不含换手率，只能用「严格早于当日」的最近流通股本估算。
若误用 coverage.last_date（可能已是今天），会整日写空并雪崩到后续交易日。
本模块提供 as-of 股本查询与缺换手回填，供 sync / 体检修复共用。

东财历史成交量为「手」、新浪/腾讯 spot 为「股」。用 ``volume/turnover`` 反推股本时
若未统一单位，股本会小 100 倍，spot 换手率可膨胀到上千百分数。反推优先用
``amount / (close * turnover)``（成交额为元，与量单位无关）。
"""
from __future__ import annotations

from datetime import date as _date
from typing import Any, Mapping, Sequence

from src.market.infrastructure.store import MarketStore
from src.market.infrastructure.turnover_math import (
    INFLATED_RATIO_HI,
    INFLATED_RATIO_LO,
    INSANE_TURNOVER,
    LOT_RATIO_HI,
    LOT_RATIO_LO,
    compute_turnover,
    normalize_trade_volume,
)

#: 倒序回看交易日上限；超过仍无股本则放弃该标的。
_ASOF_LOOKBACK_DAYS = 60
#: 单日股本覆盖达到此数量即认为足够密，可提前结束回看。
_ASOF_DENSE_CODES = 4000
#: 兼容旧名
_INSANE_TURNOVER = INSANE_TURNOVER
_LOT_RATIO_LO = LOT_RATIO_LO
_LOT_RATIO_HI = LOT_RATIO_HI
_INFLATED_RATIO_LO = INFLATED_RATIO_LO
_INFLATED_RATIO_HI = INFLATED_RATIO_HI


def _infer_shares(volume: float, turnover: float, *, amount: float | None, close: float | None) -> float | None:
    """由换手率反推流通股本（股）。

    优先 ``amount/(close*turnover)``，避免东财「手」与新浪「股」混用。

    换手率本身超过 ``INSANE_TURNOVER`` 时拒绝反推：那一行多半是单位错位的
    残留（5.0 = 500%），拿它当除数会得到小百倍的股本，再回填出一个看着
    正常、实际错 100 倍的换手率，把脏值洗成合法值。
    """
    if turnover <= 0 or turnover > INSANE_TURNOVER:
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
            "   AND turnover IS NOT NULL AND turnover > 0 AND turnover <= ?"
            "   AND volume IS NOT NULL AND volume > 0",
            (trade_date, INSANE_TURNOVER),
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


#: 滚动复用 as-of 股本时的重新播种间隔（自然日）。
#: 滚动集合只增不减，跨度一长就会留住超出 _ASOF_LOOKBACK_DAYS 回看窗的陈旧
#: 股本；每 90 个自然日（≈60 个交易日）重播一次，把陈旧上限钉死在「回看窗 +
#: 一个重播间隔」内，同时把查询量从 O(天数 × 60 日) 压到约 O(天数)。
_ASOF_RESEED_CALENDAR_DAYS = 90


class _RollingSharesAsOf:
    """按交易日**升序**滚动复用 as-of 流通股本。

    ``load_shares_asof`` 每次固定倒扫 60 个交易日（全市场约 33 万行 × 两轮
    查询）。全量修复要跑几百个交易日，逐日重算等于把同一段历史扫上百遍，而
    相邻两天的结果只差「中间新过去的那几天」。这里首日照旧全量播种，之后按
    ``[已吸收位置, 当前日)`` 增量吸收；``quotes_daily`` 以 (trade_date, code)
    聚簇，这个区间扫描是顺序读。

    调用方按日期升序调用（倒退或跨度过大会自动重新播种，不会读到「未来」
    股本）。真实 ``outstanding_share`` 永远压过反推值，与 ``load_shares_asof``
    的两轮口径一致。
    """

    def __init__(self, store: MarketStore) -> None:
        self._store = store
        self._shares: dict[str, float] = {}
        self._inferred: set[str] = set()
        self._seed_date = ""
        self._absorbed_upto = ""

    def shares_for(self, trade_date: str) -> dict[str, float]:
        """``trade_date`` 之前最近一次有效流通股本（可能复用上一日的结果）。"""
        date_s = str(trade_date or "").strip()
        if not date_s:
            return {}
        if self._needs_reseed(date_s):
            self._shares = load_shares_asof(self._store, date_s)
            self._inferred = set()
            self._seed_date = date_s
            self._absorbed_upto = date_s
            return self._shares
        if date_s > self._absorbed_upto:
            self._absorb(self._absorbed_upto, date_s)
            self._absorbed_upto = date_s
        return self._shares

    def _needs_reseed(self, date_s: str) -> bool:
        if not self._seed_date or date_s < self._absorbed_upto:
            return True
        try:
            span = _date.fromisoformat(date_s) - _date.fromisoformat(self._seed_date)
        except ValueError:
            return True
        return span.days > _ASOF_RESEED_CALENDAR_DAYS

    def _absorb(self, start: str, end: str) -> None:
        """吸收 ``[start, end)`` 区间新出现的股本；升序遍历，后写的即最近一次。"""
        rows = self._store.conn.execute(
            "SELECT code, outstanding_share FROM quotes_daily"
            " WHERE trade_date >= ? AND trade_date < ?"
            "   AND outstanding_share IS NOT NULL"
            "   AND outstanding_share > 0"
            " ORDER BY trade_date",
            (start, end),
        )
        for row in rows:
            try:
                shares = float(row[1])
            except (TypeError, ValueError):
                continue
            if shares > 0:
                code = str(row[0])
                self._shares[code] = shares
                self._inferred.discard(code)
        rows = self._store.conn.execute(
            "SELECT code, volume, turnover, amount, close FROM quotes_daily"
            " WHERE trade_date >= ? AND trade_date < ?"
            "   AND turnover IS NOT NULL AND turnover > 0 AND turnover <= ?"
            "   AND volume IS NOT NULL AND volume > 0"
            " ORDER BY trade_date",
            (start, end, INSANE_TURNOVER),
        )
        for row in rows:
            code = str(row[0])
            if code in self._shares and code not in self._inferred:
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
                self._shares[code] = shares
                self._inferred.add(code)


def backfill_missing_turnover(
    store: MarketStore,
    *,
    since: str | None = None,
    trade_dates: Sequence[str] | None = None,
    shares_asof: Mapping[str, Mapping[str, float]] | None = None,
) -> dict[str, Any]:
    """用 as-of 流通股本回填缺换手率（及缺失股本）的日 K 行。

    只改 ``outstanding_share`` / ``turnover``，不动 OHLC。
    返回 ``updated`` / ``skipped`` / ``dates_scanned``。

    ``shares_asof``：``{交易日: {code: 流通股本}}``，直接复用调用方已经算好的
    as-of 股本。``apply_today_spot`` 写当日 spot 前刚用同一个
    ``load_shares_asof(store, today)`` 算过一遍（固定倒扫 60 个交易日、约 33 万
    行），没必要在这里再算第二遍。缺哪天就现算哪天；不传时行为不变。
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

    # 升序是滚动复用的前提：两个分支都已按日期升序，这里再钉一次。
    dates = sorted(dates)
    provided = {str(key): value for key, value in (shares_asof or {}).items()}
    rolling = _RollingSharesAsOf(store)
    updated = 0
    skipped = 0
    need_where = " AND ".join(clauses[:3])  # 不含 since，按日过滤

    for trade_date in dates:
        shares_map = provided.get(trade_date)
        if shares_map is None:
            shares_map = rolling.shares_for(trade_date)
        rows = store.conn.execute(
            f"""
            SELECT code, volume, amount, close FROM quotes_daily
            WHERE trade_date = ? AND {need_where}
            """,
            (trade_date,),
        ).fetchall()
        payload: list[tuple[float, float, str, str]] = []
        for code, volume, amount, close in rows:
            shares = shares_map.get(str(code))
            if shares is None or shares <= 0:
                skipped += 1
                continue
            try:
                vol = float(volume) if volume is not None else None
                amt = float(amount) if amount is not None else None
                px = float(close) if close is not None else None
            except (TypeError, ValueError):
                skipped += 1
                continue
            turnover = compute_turnover(
                volume=vol, amount=amt, close=px, shares=shares
            )
            if turnover is None:
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
    """校正成交量单位：手×100→股，或去掉多余的 ×100。"""
    since_s = str(since).strip()
    rows = store.conn.execute(
        """
        SELECT code, trade_date, volume, amount, close
          FROM quotes_daily
         WHERE trade_date >= ?
           AND volume IS NOT NULL AND volume > 0
           AND amount IS NOT NULL AND amount > 0
           AND close IS NOT NULL AND close > 0
           AND (
             amount / (volume * close) BETWEEN ? AND ?
             OR amount / (volume * close) BETWEEN ? AND ?
           )
        """,
        (
            since_s,
            _LOT_RATIO_LO,
            _LOT_RATIO_HI,
            _INFLATED_RATIO_LO,
            _INFLATED_RATIO_HI,
        ),
    ).fetchall()
    if not rows:
        return {"scaled": 0, "since": since_s}
    payload: list[tuple[float, str, str]] = []
    for code, trade_date, volume, amount, close in rows:
        fixed = normalize_trade_volume(
            float(volume), amount=float(amount), close=float(close)
        )
        if fixed != float(volume):
            payload.append((fixed, trade_date, str(code)))
    if not payload:
        return {"scaled": 0, "since": since_s}
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


#: 科创板单日换手率超过这个值只可能是单位错位，不可能是真实成交。
_STAR_IMPOSSIBLE_TURNOVER = 1.0
#: 腾讯历史日线来源标记；spot 各板块统一为「手」，不在修复范围内。
_STAR_BUGGY_SOURCE = "tencent"


#: 同票历史线 / 现价线的成交量量级比；100 倍错位远超正常波动，20 倍已足够判定。
_STAR_SPOT_GAP = 20.0
#: 科创板代码区间；用范围比较而非 LIKE，才能走 (code, trade_date) 索引。
_STAR_CODE_LO = "688000"
_STAR_CODE_HI = "689999"
#: 探测窗口。错位是整段历史的固有属性，近窗露馅即可判定，不必扫全表。
_STAR_PROBE_DAYS = 120


def _star_probe_start(store: MarketStore) -> str:
    row = store.conn.execute(
        "SELECT MIN(trade_date) FROM ("
        " SELECT trade_date FROM trading_calendar ORDER BY trade_date DESC LIMIT ?)",
        (_STAR_PROBE_DAYS,),
    ).fetchone()
    return str(row[0] or "") if row else ""


def _inflated_star_codes(store: MarketStore) -> list[str]:
    """找出量额被 ×100 的科创板代码。

    这是**代码级**判据而非行级：单位错位是「该来源 × 该板块」的固有属性，
    一只票只要有一天露馅，它经该来源落的整段历史都是错的。行级阈值会漏掉
    真实换手不足 1% 的安静日（膨胀后仍不到 100%）。

    两条判据取并集：

    A. 有流通股本 —— 任意一天隐含换手 > 100%，物理上不可能。
    B. 缺流通股本 —— 拿该票自己的 spot 行做标尺。spot 各板块统一为「手」，
       不受本 bug 影响，所以历史线量级若比 spot 高一个数量级即为错位。
       缺了这条，像 689009 这种从未落过股本的票会整段逃过修复。

    只探测近窗：全表 ``LIKE '688%'`` + 未索引的 ``source`` 过滤会退化成千万行
    全扫（实测跑不完）；限定 ``trade_date`` 区间才能走聚簇主键顺序读。
    """
    start = _star_probe_start(store)
    scope = (
        "code >= ? AND code <= ? AND volume > 0"
        + (" AND trade_date >= ?" if start else "")
    )
    span: list[Any] = [_STAR_CODE_LO, _STAR_CODE_HI]
    if start:
        span.append(start)

    by_turnover = {
        str(row[0])
        for row in store.conn.execute(
            f"""
            SELECT code FROM quotes_daily
             WHERE {scope} AND source = ?
               AND outstanding_share IS NOT NULL AND outstanding_share > 0
             GROUP BY code
            HAVING MAX(volume / outstanding_share) > ?
            """,
            [*span, _STAR_BUGGY_SOURCE, _STAR_IMPOSSIBLE_TURNOVER],
        )
    }
    by_spot = {
        str(row[0])
        for row in store.conn.execute(
            f"""
            SELECT h.code FROM (
                SELECT code, AVG(volume) AS v FROM quotes_daily
                 WHERE {scope} AND source = ? GROUP BY code
              ) AS h
              JOIN (
                SELECT code, AVG(volume) AS v FROM quotes_daily
                 WHERE {scope} AND source LIKE '%\\_spot' ESCAPE '\\' GROUP BY code
              ) AS s ON s.code = h.code
             WHERE s.v > 0 AND h.v / s.v > ?
            """,
            [*span, _STAR_BUGGY_SOURCE, *span, _STAR_SPOT_GAP],
        )
    }
    return sorted(by_turnover | by_spot)


def rescale_star_daily_volumes(store: MarketStore, *, since: str = "") -> dict[str, Any]:
    """回正科创板历史日 K 的 100 倍量额膨胀。

    腾讯日 K 对 688/689 返回的成交量单位是「股」，旧解析一律当「手」再 ×100。
    该源的 ``amount`` 由 ``close * volume`` 合成，所以 ``amount/(volume*close)``
    恒为 1，``scale_lot_volumes`` 的比值判据永远不触发。

    **检测与更新必须在同一把写锁内**：判据虽是幂等的（回正后不再命中），但那只在
    串行下成立。多进程并发时三个副本会在任何一个提交之前读到同一份待修列表，
    各除一次 100 —— 实测把量额除成了真值的万分之一。
    """
    from src.market.infrastructure.write_lock import market_write_lock

    since_s = str(since).strip()
    with market_write_lock(store.db_path, label="star-volume-repair"):
        return _rescale_star_locked(store, since_s)


def _rescale_star_locked(store: MarketStore, since_s: str) -> dict[str, Any]:
    codes = _inflated_star_codes(store)
    if not codes:
        return {"rescaled_rows": 0, "rescaled_codes": 0, "since": since_s}

    clauses = ["source = ?", "volume > 0"]
    params: list[Any] = [_STAR_BUGGY_SOURCE]
    if since_s:
        clauses.append("trade_date >= ?")
        params.append(since_s)
    placeholders = ",".join("?" * len(codes))
    clauses.append(f"code IN ({placeholders})")
    params.extend(codes)
    where = " AND ".join(clauses)

    rows = int(
        store.conn.execute(
            f"SELECT COUNT(*) FROM quotes_daily WHERE {where}", params
        ).fetchone()[0]
        or 0
    )
    if not rows:
        return {"rescaled_rows": 0, "rescaled_codes": 0, "since": since_s}
    with store._transaction() as cursor:
        cursor.execute(
            f"""
            UPDATE quotes_daily
               SET volume = volume / 100.0,
                   amount = amount / 100.0,
                   turnover = NULL
             WHERE {where}
            """,
            params,
        )
    return {"rescaled_rows": rows, "rescaled_codes": len(codes), "since": since_s}


def repair_inflated_turnover(store: MarketStore, *, since: str) -> dict[str, Any]:
    """清空自 ``since`` 起被单位错位撑爆的换手/股本，再按正确口径回填。

    步骤：
    1. 回正科创板腾讯日 K 的 100 倍量额膨胀（比值判据盲区）
    2. 校正成交量单位（手×100，或去掉多余 ×100）
    3. 清空 spot 估出的换手/股本，以及 turnover>50% 的脏行
    4. ``backfill_missing_turnover`` 用成交额/(价×股本) 重算
    """
    since_s = str(since).strip()
    star = rescale_star_daily_volumes(store, since=since_s)
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
        "star_rescaled_rows": star["rescaled_rows"],
        "star_rescaled_codes": star["rescaled_codes"],
        "volumes_scaled": scaled["scaled"],
        "cleared": int(cleared),
        **backfill,
    }
