"""盘口 lane 取数：昨收从「全表 GROUP BY」改成「逐代码寻道」后的 parity 与边界。

四条盘口 lane（limit_up_pool / broken_limit_up / market_emotion / theme_board）
共用 ``_rows_for_date``。它原来用一个**没有下界**的 ``previous`` CTE 求每只票的
上一根日 K：真库（quotes_daily 1696 万行）EQP 实测 ``MATERIALIZE previous`` +
``SCAN quotes_daily USING COVERING INDEX idx_quotes_code_date``，一次请求扫全库
（实测 1915ms → 改后 57ms；market_emotion 还要为「昨日封板集合」再付一次）。

这个文件锁住三件事：

1. **parity**：新旧两条 SQL 在含停牌 / 新股 / 退市的合成库上逐行、逐列相等；
2. **停牌边界**：复牌首日的昨收仍是「停牌前最后一根」，不是 NULL。顺带用一条
   30 自然日下界的 CTE 变体做反例，钉死「为什么没选加固定窗口」这条路；
3. **查询计划**：实际下发的 SQL 里不再出现 ``SCAN quotes_daily``。
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sqlite3
import time
from typing import Any

import pytest

from src.market import MarketStore
from src.market.infrastructure.tape.local_provider import _rows_for_date

DAY = "2026-08-25"
#: 合成库规模：足够让「全表 GROUP BY」与「逐代码寻道」的差距压过计时噪声，
#: 又能在几秒内建完。真库是 1696 万行 / 5542 只票，这里是同形状的缩小版。
FILLER_CODES = tuple(f"6{index:05d}" for index in range(100, 500))
HISTORY_DAYS = 500

NORMAL = "600000"
HALT_SHORT = "600001"     # 停 5 个交易日后在 DAY 复牌
HALT_LONG = "600002"      # 上一根日 K 距 DAY 约 120 自然日（打穿 30 天窗口）
HALT_EXTREME = "600003"   # 上一根日 K 距 DAY 约 420 自然日（打穿 400 天窗口）
NEW_LISTING = "600004"    # 只有 DAY 一根：昨收必须是 NULL
DELISTED = "600005"   # 早就没行情：DAY 当天不该出现在结果里


# --------------------------------------------------------------- 改前的原始 SQL
# 逐字保留 ``_rows_for_date`` 改动前的两条语句，作为 parity 基准。改这两段就等于
# 改基准，等于这个文件不再证明任何东西——要改先想清楚。
def _legacy_cte_rows(
    conn: sqlite3.Connection, day: str, codes: list[str] | None = None
) -> list[dict[str, Any]]:
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    code_filter = ""
    prev_filter = ""
    params: list[Any] = [day]
    if code_list:
        placeholders = ",".join("?" for _ in code_list)
        code_filter = f" AND q.code IN ({placeholders})"
        prev_filter = f" AND code IN ({placeholders})"
        params.extend(code_list)
    params.append(day)
    if code_list:
        params.extend(code_list)
    sql = f"""
        WITH previous AS (
            SELECT code, MAX(trade_date) AS trade_date
            FROM quotes_daily
            WHERE trade_date < ?{prev_filter}
            GROUP BY code
        )
        SELECT q.code, q.trade_date, q.open, q.high, q.low, q.close,
               q.volume, q.amount, q.turnover, q.fetched_at,
               p.close AS prev_close, COALESCE(i.name, '') AS name,
               COALESCE(i.industry, '') AS industry
        FROM quotes_daily q
        LEFT JOIN previous d ON d.code = q.code
        LEFT JOIN quotes_daily p
          ON p.code = d.code AND p.trade_date = d.trade_date
        LEFT JOIN instruments i ON i.code = q.code
        WHERE q.trade_date = ?{code_filter}
        ORDER BY q.code
    """
    return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def _legacy_fallback_rows(conn: sqlite3.Connection, day: str) -> list[dict[str, Any]]:
    """改前 ``except`` 分支的兑底 SQL（每行一次 CORRELATED SCALAR SUBQUERY）。"""
    sql = """
        SELECT q.code, q.trade_date, q.open, q.high, q.low, q.close,
               q.volume, q.amount, q.turnover, q.fetched_at,
               p.close AS prev_close, '' AS name, '' AS industry
        FROM quotes_daily q
        LEFT JOIN quotes_daily p
          ON p.code = q.code
         AND p.trade_date = (
             SELECT MAX(x.trade_date) FROM quotes_daily x
             WHERE x.code = q.code AND x.trade_date < q.trade_date
         )
        WHERE q.trade_date = ?
        ORDER BY q.code
    """
    return [dict(row) for row in conn.execute(sql, (day,)).fetchall()]


def _windowed_cte_rows(
    conn: sqlite3.Connection, day: str, *, window_days: int
) -> list[dict[str, Any]]:
    """反例：给 ``previous`` CTE 加固定自然日下界的那个方案。"""
    sql = """
        WITH previous AS (
            SELECT code, MAX(trade_date) AS trade_date
            FROM quotes_daily
            WHERE trade_date < ? AND trade_date >= date(?, ?)
            GROUP BY code
        )
        SELECT q.code, p.close AS prev_close
        FROM quotes_daily q
        LEFT JOIN previous d ON d.code = q.code
        LEFT JOIN quotes_daily p
          ON p.code = d.code AND p.trade_date = d.trade_date
        WHERE q.trade_date = ?
        ORDER BY q.code
    """
    params = (day, day, f"-{window_days} days", day)
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


# -------------------------------------------------------------------- 合成数据
def _trading_days(count: int, end: str) -> list[str]:
    cursor = date.fromisoformat(end)
    days: list[str] = []
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return sorted(days)


def _before(day: str, natural_days: int) -> str:
    return (date.fromisoformat(day) - timedelta(days=natural_days)).isoformat()


def _price(code: str, index: int) -> float:
    """逐 (code, 序号) 唯一：昨收错配一格就会被 parity 抓到。"""
    return round(5.0 + (int(code[-3:]) % 89) * 0.11 + index * 0.01, 4)


def _plan_days() -> dict[str, list[str]]:
    """每只票在合成库里有哪些交易日：正常 / 短停 / 长停 / 超长停 / 新股 / 退市。"""
    days = _trading_days(HISTORY_DAYS, DAY)
    plan: dict[str, list[str]] = {code: list(days) for code in FILLER_CODES}
    plan[NORMAL] = list(days)
    plan[HALT_SHORT] = [d for d in days if d not in days[-6:-1]]
    long_gap_start = _before(DAY, 120)
    plan[HALT_LONG] = [d for d in days if d < long_gap_start or d == DAY]
    extreme_gap_start = _before(DAY, 420)
    plan[HALT_EXTREME] = [d for d in days if d < extreme_gap_start or d == DAY]
    plan[NEW_LISTING] = [DAY]
    plan[DELISTED] = [d for d in days if d < _before(DAY, 300)]
    return plan


def _seed(store: MarketStore, plan: dict[str, list[str]]) -> None:
    bars: list[dict[str, Any]] = []
    for code, code_days in plan.items():
        for index, trade_day in enumerate(code_days):
            close = _price(code, index)
            bars.append(
                {
                    "code": code,
                    "date": trade_day,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 100.0 + index,
                    "amount": close * (100.0 + index),
                }
            )
    # 只给一部分票登记 instruments：另一部分要走 LEFT JOIN 的 NULL -> '' 分支
    store.upsert_instruments(
        [
            {"code": code, "name": f"名称{code}", "industry": "本地测试"}
            for code in (NORMAL, HALT_SHORT, HALT_LONG, NEW_LISTING, *FILLER_CODES[:50])
        ]
    )
    store.upsert_quote_bars(bars, source="synthetic")


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory: pytest.TempPathFactory) -> Any:
    path: Path = tmp_path_factory.mktemp("tape_prev_close") / "market.db"
    store = MarketStore(path)
    plan = _plan_days()
    _seed(store, plan)
    rows = store.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0]
    yield store, plan, rows
    store.close()


class _Tracer:
    """记录下发的 SQL；``fail_on`` 用来逼出 ``_rows_for_date`` 的 except 分支。"""

    def __init__(self, conn: sqlite3.Connection, fail_on: str = "") -> None:
        self._conn = conn
        self.fail_on = fail_on
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        self.statements.append((sql, tuple(params)))
        if self.fail_on and self.fail_on in sql:
            raise sqlite3.OperationalError("no such column: i.name")
        return self._conn.execute(sql, params)


class _TracedStore:
    def __init__(self, conn: sqlite3.Connection, fail_on: str = "") -> None:
        self.conn = _Tracer(conn, fail_on)


# ------------------------------------------------------------------------ 测试
def test_synthetic_library_has_the_shapes_under_test(synthetic: Any) -> None:
    _store, plan, rows = synthetic
    assert rows > 150_000, "合成库太小，计时对比会淹没在噪声里"
    assert plan[NEW_LISTING] == [DAY]
    assert DAY not in plan[DELISTED]
    for code in (NORMAL, HALT_SHORT, HALT_LONG, HALT_EXTREME, NEW_LISTING):
        assert DAY in plan[code]


def test_parity_full_day(synthetic: Any) -> None:
    store, _plan, _rows = synthetic
    assert _rows_for_date(store, DAY) == _legacy_cte_rows(store.conn, DAY)


def test_parity_scoped_codes(synthetic: Any) -> None:
    store, _plan, _rows = synthetic
    codes = [HALT_LONG, HALT_EXTREME, NEW_LISTING, DELISTED, NORMAL, *FILLER_CODES[:20]]
    assert _rows_for_date(store, DAY, codes=codes) == _legacy_cte_rows(
        store.conn, DAY, codes
    )


def test_parity_on_sampled_trading_days(synthetic: Any) -> None:
    """逐日重跑：停牌前、停牌中、复牌当天三种截面都要相等。"""
    store, _plan, _rows = synthetic
    days = _trading_days(HISTORY_DAYS, DAY)
    for day in days[::37] + days[-8:]:
        assert _rows_for_date(store, day) == _legacy_cte_rows(store.conn, day), day


def test_parity_between_main_and_fallback_branch(synthetic: Any) -> None:
    """兑底分支只少 name / industry；昨收要与主查询、与改前兑底 SQL 一致。"""
    store, _plan, _rows = synthetic
    traced = _TracedStore(store.conn, fail_on="instruments")
    fallback = _rows_for_date(traced, DAY)
    assert len(traced.conn.statements) == 2, "应当先试主查询、失败后再走兑底"
    assert fallback == _legacy_fallback_rows(store.conn, DAY)
    main = _rows_for_date(store, DAY)
    assert [row["prev_close"] for row in fallback] == [
        row["prev_close"] for row in main
    ]


def test_suspension_boundary_keeps_prev_close(synthetic: Any) -> None:
    """复牌首日：昨收 = 停牌前最后一根收盘，回看不设上限。"""
    store, plan, _rows = synthetic
    rows = {row["code"]: row for row in _rows_for_date(store, DAY)}
    for code in (HALT_SHORT, HALT_LONG, HALT_EXTREME):
        expected = _price(code, len(plan[code]) - 2)
        assert rows[code]["prev_close"] == pytest.approx(expected), code
        last_before = date.fromisoformat(plan[code][-2])
        assert (date.fromisoformat(DAY) - last_before).days > 1
    extreme_gap = date.fromisoformat(DAY) - date.fromisoformat(plan[HALT_EXTREME][-2])
    assert extreme_gap.days > 400, "超长停牌样本没造出来，这条测试就不算数了"


def test_fixed_natural_day_window_would_silently_drop_resumptions(
    synthetic: Any,
) -> None:
    """反例：这就是「给 CTE 加 30 天下界」被否掉的原因，不是口味问题。"""
    store, _plan, _rows = synthetic
    windowed = {
        row["code"]: row["prev_close"]
        for row in _windowed_cte_rows(store.conn, DAY, window_days=30)
    }
    exact = {row["code"]: row["prev_close"] for row in _rows_for_date(store, DAY)}
    # 30 天窗口把两只长停牌票的昨收抹成 NULL：不抛错，只是当天少两只票的涨跌幅
    assert windowed[HALT_LONG] is None
    assert windowed[HALT_EXTREME] is None
    assert exact[HALT_LONG] is not None
    assert exact[HALT_EXTREME] is not None
    # 短停牌票落在窗口内，所以窗口方案「大部分时候看着是对的」——这才是它危险的地方
    assert windowed[HALT_SHORT] == exact[HALT_SHORT]


def test_new_listing_and_delisted_rows(synthetic: Any) -> None:
    store, _plan, _rows = synthetic
    rows = {row["code"]: row for row in _rows_for_date(store, DAY)}
    assert rows[NEW_LISTING]["prev_close"] is None, "新股没有昨收，禁止瞎补"
    assert DELISTED not in rows, "退市票当天没有行，不该混进盘口截面"
    assert rows[NORMAL]["name"] == f"名称{NORMAL}"
    assert rows[HALT_EXTREME]["name"] == "", "未登记 instruments 的票要落到空串"


def test_query_plan_has_no_full_scan(synthetic: Any) -> None:
    store, _plan, _rows = synthetic
    traced = _TracedStore(store.conn)
    _rows_for_date(traced, DAY)
    sql, params = traced.conn.statements[-1]
    plan_rows = store.conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    plan_text = "\n".join(str(row[3]) for row in plan_rows)
    assert "SCAN quotes_daily" not in plan_text, plan_text
    assert "MATERIALIZE" not in plan_text, plan_text
    assert "SEARCH q USING PRIMARY KEY" in plan_text, plan_text
    assert "idx_quotes_code_date" in plan_text, plan_text


def test_legacy_plan_did_scan_the_whole_table(synthetic: Any) -> None:
    """对照组：同一个库上，改前那条 SQL 的计划确实是全表扫。"""
    store, _plan, _rows = synthetic
    plan_rows = store.conn.execute(
        "EXPLAIN QUERY PLAN"
        " WITH previous AS (SELECT code, MAX(trade_date) AS trade_date"
        " FROM quotes_daily WHERE trade_date < ? GROUP BY code)"
        " SELECT q.code, p.close FROM quotes_daily q"
        " LEFT JOIN previous d ON d.code = q.code"
        " LEFT JOIN quotes_daily p ON p.code = d.code AND p.trade_date = d.trade_date"
        " WHERE q.trade_date = ? ORDER BY q.code",
        (DAY, DAY),
    ).fetchall()
    plan_text = "\n".join(str(row[3]) for row in plan_rows)
    assert "SCAN quotes_daily" in plan_text, plan_text


def test_new_query_is_faster_than_the_legacy_cte(synthetic: Any) -> None:
    store, _plan, rows = synthetic

    def best(fn: Any) -> float:
        timings = []
        for _ in range(3):
            start = time.perf_counter()
            fn()
            timings.append((time.perf_counter() - start) * 1000.0)
        return min(timings)

    legacy_ms = best(lambda: _legacy_cte_rows(store.conn, DAY))
    new_ms = best(lambda: _rows_for_date(store, DAY))
    print(
        f"\n[prev_close] 合成库 {rows} 行 / {len(FILLER_CODES) + 6} 只票："
        f"改前 {legacy_ms:.1f} ms -> 改后 {new_ms:.1f} ms"
        f"（{legacy_ms / new_ms:.1f}x）"
    )
    assert new_ms * 3 < legacy_ms, f"legacy={legacy_ms:.1f}ms new={new_ms:.1f}ms"
