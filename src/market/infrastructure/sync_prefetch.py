r"""同步前置状态预热：把逐票点查换成几条全市场聚合。

``sync_quotes`` 过去对每只票各做 4 条点查（watermark / 库内最早日 / 最后一根
非 spot 日 K / 复权因子时间）。全市场 5500 只就是约 2.2 万次查询，其中
「最后一根非 spot」还是 ``source NOT LIKE`` 这种索引不友好的形态。

真实 1700 万行库上的实测：

- watermark 全表         5547 次点查 -> 一次 0.03s
- 库内最早日 + 最后一日   11094 次点查 -> 一次 2.26s
- 最后一根非 spot（全表） 5547 次点查 -> 一次 277.56s（不可用）
- 最后一根非 spot（近窗） 同上         -> 一次 0.38s
- 复权因子时间           5547 次点查 -> 一次 0.02s

「最后一根非 spot」必须给 ``trade_date`` 上下界才快：``quotes_daily`` 主键是
``(trade_date, code)`` 且 ``WITHOUT ROWID``，按日期聚簇。给了界是顺序读，
不给界优化器只能全表扫 1700 万行。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import time
from typing import Any

from src.shared.clock import utc_now


#: 非 spot 末日的回看窗口。比增量判据的最大断档容忍宽一截即可：窗口里查不到
#: 非 spot 行，说明这票定稿历史已落后超过窗口，增量判据本来也会判它走全量。
FINALIZED_LOOKBACK_DAYS = 400
_LISTING_SKIP_SOURCE = "listing_calendar"


@dataclass
class SyncPrefetch:
                """一次同步开始时的全市场状态快照。

                只读；只在同步启动时算一次，worker 线程并发读它，不再回库点查。
                """

                watermarks: dict[str, dict[str, Any]] = field(default_factory=dict)
                earliest: dict[str, str] = field(default_factory=dict)
                finalized_last: dict[str, str] = field(default_factory=dict)
                #: 证券列表给出的上市日；新股上市当日通常还没有定稿日 K。
                list_dates: dict[str, str] = field(default_factory=dict)
                factor_age: dict[str, str] = field(default_factory=dict)
                #: 非 spot 末日窗口起点；窗口外的票按「无定稿末日」处理。
                finalized_window_start: str = ""
                elapsed_seconds: float = 0.0
                #: 预热是否真的拿到了数据。库形态异常时全空，调用方回落逐票点查。
                loaded: bool = False

                def watermark(self, code: str) -> dict[str, Any] | None:
                                return self.watermarks.get(code)


def listing_day_without_history(
                prefetch: SyncPrefetch, code: str, *, today: str
) -> str:
                """返回仍在上市日且没有定稿日 K 的上市日期，否则返回空串。"""
                list_date = str(prefetch.list_dates.get(code) or "")[:10]
                if not list_date:
                                return ""
                try:
                                if date.fromisoformat(list_date) < date.fromisoformat(today):
                                                return ""
                except ValueError:
                                return ""
                if prefetch.finalized_last.get(code, ""):
                                return ""
                return list_date


def listing_day_skip_receipt(
                code: str, list_date: str, *, today: str
) -> dict[str, Any]:
                """新股上市日尚无定稿日 K 时的可观测跳过回执。"""
                reason = f"上市日 {list_date} 暂无定稿日 K，跳过历史源请求；收盘后再同步"
                return {
                                "code": code,
                                "lane": "hist_daily",
                                "attempts": [
                                                {
                                                                "source_id": _LISTING_SKIP_SOURCE,
                                                                "state": "skipped",
                                                                "checked_at": utc_now(),
                                                                "error": reason,
                                                }
                                ],
                                "selected_source": "",
                                "fallback_used": False,
                                "unresolved": False,
                                "coverage_start": list_date,
                                "coverage_end": today,
                                "request_start": list_date,
                                "request_end": today,
                                "error": reason,
                                "watermark": {
                                                "status": "ok",
                                                "message": reason,
                                                "source": _LISTING_SKIP_SOURCE,
                                },
                }


def _rows(store: Any, sql: str, params: tuple = ()) -> list[tuple]:
                """预热是纯加速：库形态异常时返回空，让调用方退回逐票点查。"""
                try:
                                return list(store.conn.execute(sql, params).fetchall())
                except Exception:
                                return []


_WATERMARK_SQL = (
                "SELECT code, last_trade_date, last_synced_at, status, source, message"
                " FROM ingest_watermark"
)
_EARLIEST_SQL = "SELECT code, MIN(trade_date) FROM quotes_daily GROUP BY code"
_FINALIZED_SQL = (
                "SELECT code, MAX(trade_date) FROM quotes_daily"
                " WHERE trade_date >= ? AND trade_date <= ?"
                " AND source NOT LIKE '%\\_spot' ESCAPE '\\' GROUP BY code"
)
_LIST_DATE_SQL = (
                "SELECT code, list_date FROM instruments"
                " WHERE COALESCE(list_date, '') <> ''"
)
_FACTOR_SQL = "SELECT code, MAX(fetched_at) FROM adjust_factors GROUP BY code"


def load_sync_prefetch(
                store: Any,
                *,
                today: date | None = None,
                lookback_days: int = FINALIZED_LOOKBACK_DAYS,
) -> SyncPrefetch:
                """跑几条全市场聚合，装成 worker 可并发只读的 dict。"""
                began = time.perf_counter()
                anchor = today or date.today()
                window_start = (anchor - timedelta(days=max(1, lookback_days))).isoformat()
                window_end = anchor.isoformat()
                out = SyncPrefetch(finalized_window_start=window_start)

                for row in _rows(store, _WATERMARK_SQL):
                                out.watermarks[str(row[0])] = {
                                                "code": str(row[0]),
                                                "last_trade_date": row[1],
                                                "last_synced_at": row[2],
                                                "status": row[3],
                                                "source": row[4],
                                                "message": row[5],
                                }
                for row in _rows(store, _EARLIEST_SQL):
                                out.earliest[str(row[0])] = str(row[1] or "")[:10]
                for row in _rows(store, _FINALIZED_SQL, (window_start, window_end)):
                                out.finalized_last[str(row[0])] = str(row[1] or "")[:10]
                for row in _rows(store, _LIST_DATE_SQL):
                                out.list_dates[str(row[0])] = str(row[1] or "")[:10]
                for row in _rows(store, _FACTOR_SQL):
                                out.factor_age[str(row[0])] = str(row[1] or "")

                out.loaded = bool(out.watermarks or out.earliest or out.list_dates)
                out.elapsed_seconds = time.perf_counter() - began
                return out
