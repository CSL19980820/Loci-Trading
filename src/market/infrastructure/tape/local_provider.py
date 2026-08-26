"""基于 market.db 日线缓存的盘口情报降级 provider。

这里不把日线缓存伪装成盘中实时数据。能从同一交易日 OHLCV 严格推导的
宽度、涨跌停、炸板和一日晋级才计算；题材榜只做带告警的行业派生，
竞价没有可靠本地等价物时明确返回 degraded。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import floor, isfinite
from typing import Any

from src.formula import limit_ratio_for
from src.market.domain.tape import TapeProvenance, TapeRequest, TapeResult
from src.market.infrastructure.adapters.types import (
    LANE_AUCTION_SNAPSHOT,
    LANE_BROKEN_LIMIT_UP,
    LANE_LIMIT_UP_POOL,
    LANE_MARKET_EMOTION,
    LANE_THEME_BOARD,
    LANE_THEME_MEMBERS,
    TAPE_LANES,
)
from src.market.infrastructure.tape.local_theme import (
    LOCAL_THEME_WARNING,
    build_local_theme_payload,
)

_UNSUPPORTED_WARNINGS = {LANE_AUCTION_SNAPSHOT: "local_auction_unavailable"}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _round_price(value: float) -> float:
    """与公式域 ZTPRICE 一致，避免 Python banker rounding。"""
    return floor(value * 100.0 + 0.5 + 1e-9) / 100.0


def _limit_price(row: Mapping[str, Any], *, direction: int) -> float | None:
    previous = _number(row.get("prev_close"))
    if previous is None or previous <= 0:
        return None
    ratio = limit_ratio_for(str(row.get("code") or ""), str(row.get("name") or ""))
    return _round_price(previous * (1.0 + direction * ratio))


#: 涨跌停价与行情报价都精确到分，只需吸收浮点/取整噪声。原来的 0.5% 相对容差
#: 会把「+9.5% 且收在最高价」记成涨停，直接虚增涨停家数与梯队高度。
_PRICE_EPSILON = 0.005


def _limit_flags(row: Mapping[str, Any]) -> tuple[bool, bool]:
    """返回 (触及涨停, 封住涨停)。缺昨收时不猜价格。"""
    target = _limit_price(row, direction=1)
    close = _number(row.get("close"))
    high = _number(row.get("high"))
    if target is None or close is None or high is None:
        return False, False
    touched = high >= target - _PRICE_EPSILON
    sealed = touched and close >= target - _PRICE_EPSILON and abs(close - high) <= 1e-8
    return touched, sealed


def _limit_down(row: Mapping[str, Any]) -> bool:
    target = _limit_price(row, direction=-1)
    close = _number(row.get("close"))
    low = _number(row.get("low"))
    if target is None or close is None or low is None:
        return False
    return close <= target + _PRICE_EPSILON and abs(close - low) <= 1e-8


def _store_from_request(request: TapeRequest) -> tuple[Any | None, bool]:
    context = request.context if isinstance(request.context, Mapping) else {}
    store = context.get("market_store") or context.get("store")
    if store is not None:
        return store, False
    try:
        from src.market.infrastructure.store import MarketStore
        from src.shared.paths import market_db, market_hot_db

        for path in (market_hot_db(), market_db()):
            if path.is_file():
                return MarketStore(path), True
    except Exception:
        pass
    return None, False


def _close_owned(store: Any, owned: bool) -> None:
    if not owned:
        return
    try:
        store.close()
    except Exception:
        pass


def _theme_quote_probe(store: Any, day: str) -> tuple[bool, str]:
    """题材可用性轻探测：不拉全日行情行。"""
    if not day:
        return False, "local_theme_quotes_unavailable"
    has_quote = store.conn.execute(
        "SELECT 1 FROM quotes_daily WHERE trade_date = ? LIMIT 1",
        (day,),
    ).fetchone()
    if has_quote is None:
        return False, "local_theme_quotes_unavailable"
    has_industry = store.conn.execute(
        "SELECT 1 FROM instruments WHERE COALESCE(industry, '') != '' LIMIT 1"
    ).fetchone()
    if has_industry is None:
        return False, "local_theme_industry_missing"
    return True, LOCAL_THEME_WARNING


def _latest_date(store: Any) -> str:
    row = store.conn.execute("SELECT MAX(trade_date) AS trade_date FROM quotes_daily").fetchone()
    return str(row["trade_date"] or "") if row else ""


def _target_date(store: Any, requested: str | None) -> tuple[str, bool]:
    requested_day = str(requested or "").strip()[:10]
    if requested_day:
        row = store.conn.execute(
            "SELECT 1 FROM quotes_daily WHERE trade_date = ? LIMIT 1", (requested_day,)
        ).fetchone()
        if row is not None:
            return requested_day, False
    latest = _latest_date(store)
    return latest, bool(requested_day and latest and latest != requested_day)


def _resolve_day(store: Any, request: TapeRequest) -> tuple[str, bool]:
    """优先复用 request.as_of_date（is_available / 上游已探测），避免重算交易日。"""
    as_of = str(request.as_of_date or "").strip()[:10]
    if as_of:
        requested_day = str(request.requested_date or "").strip()[:10]
        return as_of, bool(requested_day and as_of != requested_day)
    return _target_date(store, request.requested_date)


#: 昨收取数：逐代码在 ``idx_quotes_code_date`` 上做一次 ``(code, < 当日)`` 上界寻道。
#:
#: 旧写法是 ``WITH previous AS (SELECT code, MAX(trade_date) FROM quotes_daily
#: WHERE trade_date < ? GROUP BY code)``——没有下界。真库（1696 万行）EQP 实测
#: ``MATERIALIZE previous`` + ``SCAN quotes_daily USING COVERING INDEX
#: idx_quotes_code_date``：为了给当日 5542 只票各配一个昨收，先把全表目录扫一遍
#: （1950ms）。四条盘口 lane 共用这个入口，market_emotion 还要为「昨日封板集合」
#: 再调一次，一次情绪请求付两遍全库扫。
#:
#: 为什么不改成「给 CTE 加自然日下界」或「先查 trading_calendar 求上一交易日」：
#: 两者都会在**停牌边界**上改变结果。复牌那天个股的上一根日 K 不是上一个交易日，
#: 真库实测 2020 年以来仍有 113 个「距上一根日 K 超过 30 自然日」的复牌日
#: （2021 年最长 468 天，全历史最长 1016 天）。窗口取小了，复牌首日 prev_close
#: 变 NULL——涨跌幅、涨跌停判定、情绪宽度当场少一只票且不报错；窗口取大了
#: （400 天实测 1278ms）又基本没省下什么。逐代码寻道没有这个取舍：回看无上限、
#: 与旧 SQL 逐行相等，代价是 O(当日票数 × log 总行数) 次索引下潜（5542 只票实测
#: 约 60ms）。改这段前先跑 tests/market/test_tape_prev_close_scan.py 的 parity。
_PREV_CLOSE_SQL = """(
                    SELECT x.close FROM quotes_daily x
                     WHERE x.code = q.code AND x.trade_date < q.trade_date
                     ORDER BY x.trade_date DESC LIMIT 1
               ) AS prev_close"""

_ROW_COLUMNS = """q.code, q.trade_date, q.open, q.high, q.low, q.close,
               q.volume, q.amount, q.turnover, q.fetched_at"""


def _rows_for_date(
    store: Any,
    day: str,
    *,
    codes: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """取一日原始 OHLCV，并在应用层补上昨收。

    ``codes`` 非空时只拉指定代码（theme_members 等窄车道），避免全市场 JOIN。
    昨收取法见 ``_PREV_CLOSE_SQL``：逐代码寻道，不做全表 GROUP BY。
    """
    if not day:
        return []
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    code_filter = ""
    params: list[Any] = [day]
    if code_list:
        placeholders = ",".join("?" for _ in code_list)
        code_filter = f" AND q.code IN ({placeholders})"
        params.extend(code_list)
    sql = f"""
        SELECT {_ROW_COLUMNS},
               {_PREV_CLOSE_SQL},
               COALESCE(i.name, '') AS name,
               COALESCE(i.industry, '') AS industry
        FROM quotes_daily q
        LEFT JOIN instruments i ON i.code = q.code
        WHERE q.trade_date = ?{code_filter}
        ORDER BY q.code
    """
    try:
        rows = store.conn.execute(sql, tuple(params)).fetchall()
    except Exception:
        # 最小 fake store / 老库可能没有 instruments.name，行情仍可降级计算。
        # 昨收表达式与主查询共用同一个常量，兑底分支不会长出第二套语义。
        rows = store.conn.execute(
            f"""
            SELECT {_ROW_COLUMNS},
                   {_PREV_CLOSE_SQL},
                   '' AS name, '' AS industry
            FROM quotes_daily q
            WHERE q.trade_date = ?{code_filter}
            ORDER BY q.code
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def _theme_member_codes(store: Any, request: TapeRequest) -> list[str] | None:
    """theme_members：先定行业/代码再取行；定不了则退回全日（兼容旧探测）。"""
    from src.market.infrastructure.tape.local_theme import (
        _code,
        _industry,
        _instrument_rows,
        _requested_codes,
        _selected_industries,
    )

    instruments = _instrument_rows(store)
    selected = _selected_industries(request, instruments, [])
    requested_codes = _requested_codes(request)
    if requested_codes:
        return sorted(requested_codes)
    if not selected:
        return None
    return sorted(
        {
            _code(row.get("code"))
            for row in instruments
            if _industry(row.get("industry")) in selected and _code(row.get("code"))
        }
    )


def _pct_chg(row: Mapping[str, Any]) -> float | None:
    close = _number(row.get("close"))
    previous = _number(row.get("prev_close"))
    if close is None or previous is None or previous <= 0:
        return None
    return (close / previous - 1.0) * 100.0


def _trade_meta(day: str, *, stale: bool, fetched_at: str = "") -> dict[str, Any]:
    return {
        "tradeDate": day,
        "actualTradeDate": day,
        "dateStatus": "mismatch" if stale else "exact",
        "isRealtime": False,
        "dataFreshness": {"isRealtime": False},
        **({"snapshotTime": fetched_at} if fetched_at else {}),
        "source": "market_daily_cache",
    }


def _with_pct(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    pct = _pct_chg(row)
    if pct is not None:
        result["pct_chg"] = round(pct, 4)
        result["pctChg"] = round(pct, 4)
    return result


def _streak_levels(store: Any, rows: list[dict[str, Any]], day: str) -> dict[str, int]:
    """只对当前封板票计算已被缓存 OHLCV 证明的连续封板高度。"""
    candidates = [str(row.get("code") or "") for row in rows if _limit_flags(row)[1]]
    candidates = list(dict.fromkeys(code for code in candidates if code))
    if not candidates:
        return {}
    try:
        dates = [
            str(row[0])
            for row in store.conn.execute(
                "SELECT DISTINCT trade_date FROM quotes_daily WHERE trade_date <= ? "
                "ORDER BY trade_date DESC LIMIT 16",
                (day,),
            ).fetchall()
        ]
        placeholders = ",".join("?" for _ in candidates)
        date_placeholders = ",".join("?" for _ in dates)
        history = store.conn.execute(
            f"""
            SELECT q.code, q.trade_date, q.high, q.low, q.close,
                   p.close AS prev_close, COALESCE(i.name, '') AS name
            FROM quotes_daily q
            LEFT JOIN quotes_daily p
              ON p.code = q.code
             AND p.trade_date = (
                 SELECT MAX(x.trade_date) FROM quotes_daily x
                 WHERE x.code = q.code AND x.trade_date < q.trade_date
             )
            LEFT JOIN instruments i ON i.code = q.code
            WHERE q.code IN ({placeholders})
              AND q.trade_date IN ({date_placeholders})
            ORDER BY q.code, q.trade_date
            """,
            [*candidates, *dates],
        ).fetchall()
    except Exception:
        # 查不到历史就交空表：单票缺失由调用方按「已封板至少 1 板」兜底，
        # 但整表填 1 会让 max() 算出「今日最高板 = 1」这种看不出错的假市况。
        return {}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in history:
        grouped.setdefault(str(row["code"]), []).append(dict(row))
    levels: dict[str, int] = {}
    for code in candidates:
        series = grouped.get(code, [])
        level = 0
        for row in reversed(series):
            touched, sealed = _limit_flags(row)
            if not touched or not sealed:
                break
            level += 1
        if level:
            levels[code] = level
    return levels


def _emotion_payload(store: Any, day: str, *, stale: bool, rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [(_with_pct(row), _limit_flags(row)) for row in rows]
    changes = [pct for row, _flags in valid if (pct := _pct_chg(row)) is not None]
    up = sum(1 for pct in changes if pct > 0)
    down = sum(1 for pct in changes if pct < 0)
    touched = sum(1 for _row, flags in valid if flags[0])
    sealed = sum(1 for _row, flags in valid if flags[1])
    limit_down = sum(1 for row, _flags in valid if _limit_down(row))
    previous_day = ""
    if rows:
        previous_day = str(
            store.conn.execute(
                "SELECT MAX(trade_date) FROM quotes_daily WHERE trade_date < ?", (day,)
            ).fetchone()[0]
            or ""
        )
    previous_rows = _rows_for_date(store, previous_day) if previous_day else []
    previous_sealed = {
        str(row.get("code") or "") for row in previous_rows if _limit_flags(row)[1]
    }
    current_sealed = {
        str(row.get("code") or "") for row in rows if _limit_flags(row)[1]
    }
    payload: dict[str, Any] = {
        **_trade_meta(day, stale=stale, fetched_at=str(rows[0].get("fetched_at") or "")),
        "breadth": up / (up + down) if up + down else None,
        "limit_up_count": sealed,
        "limit_down_count": limit_down,
        "broken_rate": (touched - sealed) / touched if touched else None,
        "promotion_rate": (
            len(previous_sealed & current_sealed) / len(previous_sealed)
            if previous_sealed
            else None
        ),
        "height": max(_streak_levels(store, rows, day).values(), default=None),
        "universe_count": len(rows),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _limit_up_payload(
    store: Any,
    day: str,
    *,
    stale: bool,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    levels = _streak_levels(store, rows, day)
    output: list[dict[str, Any]] = []
    for raw in rows:
        touched, sealed = _limit_flags(raw)
        if not sealed:
            continue
        row = _with_pct(raw)
        row.update(
            {
                "isLimitUp": True,
                "ladder_level": levels.get(str(row.get("code") or ""), 1),
                "level": levels.get(str(row.get("code") or ""), 1),
            }
        )
        output.append(row)
    summary: dict[str, int] = {}
    for row in output:
        level = int(row["level"])
        summary[str(level)] = summary.get(str(level), 0) + 1
    return {
        **_trade_meta(day, stale=stale, fetched_at=str(rows[0].get("fetched_at") or "")),
        "highestBoard": max((int(row["level"]) for row in output), default=None),
        "boardSummary": [
            {"level": int(level), "count": count}
            for level, count in sorted(summary.items(), key=lambda item: int(item[0]), reverse=True)
        ],
        "rows": output,
    }


def _broken_payload(
    day: str,
    *,
    stale: bool,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    output: list[dict[str, Any]] = []
    for raw in rows:
        touched, sealed = _limit_flags(raw)
        if not touched or sealed:
            continue
        row = _with_pct(raw)
        row["isBrokenLimitUp"] = True
        output.append(row)
    return {
        **_trade_meta(day, stale=stale, fetched_at=str(rows[0].get("fetched_at") or "")),
        "rows": output,
    }


class LocalTapeProvider:
    """从现有行情缓存提供不编造的 tape 降级结果。"""

    provider_id = "local"
    label = "本地行情缓存"
    lanes = TAPE_LANES

    def __init__(self, market_store: Any | None = None) -> None:
        self.market_store = market_store

    def supports(self, lane: str) -> bool:
        return lane in self.lanes

    def is_available(self, request: TapeRequest) -> tuple[bool, str]:
        if request.lane in _UNSUPPORTED_WARNINGS:
            return False, _UNSUPPORTED_WARNINGS[request.lane]
        store, owned = _store_from_request(
            request if self.market_store is None else _request_with_store(request, self.market_store)
        )
        if store is None:
            return False, "local_market_store_unavailable"
        try:
            latest = _latest_date(store)
            if not latest:
                return False, "local_cache_empty"
            if request.lane in {LANE_THEME_BOARD, LANE_THEME_MEMBERS}:
                day, _stale = _resolve_day(store, request)
                return _theme_quote_probe(store, day)
            return True, ""
        except Exception as exc:
            return False, f"local_cache_unreadable:{type(exc).__name__}"
        finally:
            _close_owned(store, owned)

    def _unavailable(self, request: TapeRequest, reason: str) -> TapeResult:
        return TapeResult(
            data=None,
            provenance=TapeProvenance(
                provider_id=self.provider_id,
                lane=request.lane,
                requested_date=request.requested_date,
                as_of_date=request.as_of_date,
                degraded=True,
                warnings=(reason,),
            ),
            error=reason,
        )

    def fetch(self, request: TapeRequest) -> TapeResult:
        if request.lane in _UNSUPPORTED_WARNINGS:
            return self._unavailable(request, _UNSUPPORTED_WARNINGS[request.lane])
        effective = (
            request
            if self.market_store is None
            else _request_with_store(request, self.market_store)
        )
        store, owned = _store_from_request(effective)
        if store is None:
            return self._unavailable(request, "local_market_store_unavailable")
        try:
            day, stale = _resolve_day(store, request)
            if not day:
                return self._unavailable(request, "local_cache_empty")
            # 先分流再取行：theme_members 只拉成分代码，避免全市场 JOIN
            row_codes: Sequence[str] | None = None
            if request.lane == LANE_THEME_MEMBERS:
                row_codes = _theme_member_codes(store, request)
            rows = _rows_for_date(store, day, codes=row_codes)
            if not rows:
                return self._unavailable(request, "local_cache_empty")
            if request.lane in {LANE_THEME_BOARD, LANE_THEME_MEMBERS}:
                data, warnings, error = build_local_theme_payload(
                    store,
                    request,
                    day=day,
                    stale=stale,
                    rows=rows,
                )
                if data is None:
                    return self._unavailable(request, error or LOCAL_THEME_WARNING)
                return TapeResult(
                    data=data,
                    provenance=TapeProvenance(
                        provider_id=self.provider_id,
                        lane=request.lane,
                        requested_date=request.requested_date,
                        as_of_date=day,
                        degraded=True,
                        stale=stale,
                        warnings=tuple(dict.fromkeys((*warnings, LOCAL_THEME_WARNING))),
                    ),
                    error=error,
                )
            if request.lane == LANE_MARKET_EMOTION:
                data = _emotion_payload(store, day, stale=stale, rows=rows)
            elif request.lane == LANE_LIMIT_UP_POOL:
                data = _limit_up_payload(store, day, stale=stale, rows=rows)
            elif request.lane == LANE_BROKEN_LIMIT_UP:
                data = _broken_payload(day, stale=stale, rows=rows)
            else:
                return self._unavailable(request, "unsupported_tape_lane")
            return TapeResult(
                data=data,
                provenance=TapeProvenance(
                    provider_id=self.provider_id,
                    lane=request.lane,
                    requested_date=request.requested_date,
                    as_of_date=day,
                    degraded=stale,
                    stale=stale,
                    warnings=("local_date_mismatch",) if stale else (),
                ),
            )
        except Exception as exc:
            return self._unavailable(request, f"local_cache_failed:{type(exc).__name__}")
        finally:
            _close_owned(store, owned)


def _request_with_store(request: TapeRequest, store: Any) -> TapeRequest:
    context = dict(request.context) if isinstance(request.context, Mapping) else {}
    context["market_store"] = store
    return TapeRequest(
        lane=request.lane,
        requested_date=request.requested_date,
        as_of_date=request.as_of_date,
        tool=request.tool,
        codes=request.codes,
        limit=request.limit,
        arguments=request.arguments,
        params=request.params,
        context=context,
        cache=request.cache,
        cache_max_age_minutes=request.cache_max_age_minutes,
    )


__all__ = ["LocalTapeProvider"]
