"""历史日期选股的存储选择：热库必须覆盖目标日的完整指标预热日历。

只看「相对今天」的窗口深度与末日，会让历史日选股静默少票：
``screener._resolve_start`` 的 ``max(0, len(days) - bars)`` 把预热起点无声钳位到
热库首日，随后 ``load_panel(min_bars=...)`` 把历史不够的票直接丢掉，结果照常入库。
这些用例锁住那条曾被四个入口漏掉的判据。
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from src.market import MarketStore, hot_fallback_reason

_QUOTES_COLUMNS = (
    "trade_date, code, open, high, low, close, volume, amount, "
    "outstanding_share, turnover, source, receipt_id, fetched_at"
)
_QUOTE_PLACEHOLDERS = ",".join("?" * 13)
_CODE = "000001"

#: 窗口深度判据在这些用例里必须**放行**，否则「热库窗口偏浅」会盖住预热日历的
#: 结论。测试库只有几十天，用 10 天窗口让前两条判据稳定通过。
_WINDOW = 10


def _day(index: int) -> str:
    return (date(2026, 1, 1) + timedelta(days=index)).isoformat()


class HotFallbackReasonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.full = MarketStore(root / "market.db")
        self.hot = MarketStore(root / "market_hot.db")
        self._fill(self.full, range(0, 60))
        self._fill(self.hot, range(40, 60))

    def tearDown(self) -> None:
        self.full.close()
        self.hot.close()
        self.temp.cleanup()

    def _fill(self, store: MarketStore, indexes) -> None:
        days = [_day(i) for i in indexes]
        store.upsert_instruments(
            [
                {
                    "code": _CODE,
                    "name": "测试票",
                    "market": "SZ",
                    "instrument_type": "STOCK",
                }
            ]
        )
        store.conn.executemany(
            "INSERT INTO trading_calendar(trade_date, updated_at) VALUES(?, ?)",
            [(day, f"{day}T00:00:00") for day in days],
        )
        store.conn.executemany(
            f"INSERT INTO quotes_daily({_QUOTES_COLUMNS}) VALUES({_QUOTE_PLACEHOLDERS})",
            [
                (
                    day, _CODE, 10.0, 10.5, 9.8, 10.2, 1000, 10000, None, None,
                    "test", None, f"{day}T00:00:00",
                )
                for day in days
            ],
        )
        store.conn.commit()

    def _drop_from_hot(self, index: int) -> None:
        """从热库同时删掉某天的日历与日 K，模拟增量镜像留下的日历缺口。"""
        day = _day(index)
        self.hot.conn.execute("DELETE FROM trading_calendar WHERE trade_date = ?", (day,))
        self.hot.conn.execute("DELETE FROM quotes_daily WHERE trade_date = ?", (day,))
        self.hot.conn.commit()

    def _reason(self, **kwargs) -> str:
        params: dict = {"window_trading_days": _WINDOW}
        params.update(kwargs)
        return hot_fallback_reason(self.full, self.hot, **params)

    def test_target_day_before_hot_window_falls_back(self) -> None:
        """目标日整个落在热库窗口之外 → 必须回退全量库。

        不拦住它，screener 会拿到空的 days 并抛「行情仓没有任何交易日数据，请先
        执行同步」——而全量库里那段历史好得很，误导性比少票更强。
        """
        reason = self._reason(trade_date=_day(10), warmup_bars=5)
        self.assertIn("热库未覆盖目标日预热窗口", reason)

    def test_target_day_inside_window_but_warmup_short_falls_back(self) -> None:
        """目标日在热库里，但它前面的预热日历伸到窗口外 → 仍要回退。

        这是最容易漏的一种：目标日查得到、面板也跑得出来，只是每只票的历史比
        策略要求的短，指标从半截开始递推，少票且信号漂移，且不报任何错。
        """
        reason = self._reason(trade_date=_day(42), warmup_bars=10)
        self.assertIn("热库未覆盖目标日预热窗口", reason)

    def test_full_coverage_uses_hot(self) -> None:
        """目标日与完整预热窗口都在热库内 → 空串，照常读热库。"""
        self.assertEqual(self._reason(trade_date=_day(50), warmup_bars=5), "")

    def test_missing_day_after_target_in_range_falls_back(self) -> None:
        """区间选股：预热段完好，但区间后半段缺一天 → 回退。

        区间末日由 ``end`` 传入；只校验到 trade_date 为止会漏掉这一段。
        """
        self._drop_from_hot(52)
        reason = self._reason(trade_date=_day(45), warmup_bars=3, end=_day(55))
        self.assertIn("热库未覆盖目标日预热窗口", reason)

    def test_missing_day_inside_warmup_falls_back(self) -> None:
        """预热区间**中间**缺一天 → 回退。

        增量镜像允许日历缺口，窗口起点与天数都看不出中间少了一天。
        """
        self._drop_from_hot(48)
        reason = self._reason(trade_date=_day(50), warmup_bars=5)
        self.assertIn("热库未覆盖目标日预热窗口", reason)

    def test_stale_hot_still_rejected(self) -> None:
        """``hot_unusable_reason`` 的末日判据必须保留，不能被新判据挤掉。"""
        self._fill(self.full, [60])
        reason = self._reason(trade_date=_day(55), warmup_bars=3)
        self.assertIn("落后", reason)

    def test_live_overlay_skips_stale_check_but_keeps_warmup(self) -> None:
        """盘中 overlay 跳过末日判据（今日价走实时），预热日历照查。"""
        self._fill(self.full, [60])
        self.assertEqual(
            self._reason(trade_date=_day(55), warmup_bars=3, live_overlay=True), ""
        )
        reason = self._reason(trade_date=_day(10), warmup_bars=3, live_overlay=True)
        self.assertIn("热库未覆盖目标日预热窗口", reason)

    def test_no_history_before_target_day(self) -> None:
        """目标日早于全量库首日 → 连预热窗口都取不到。"""
        reason = self._reason(trade_date="2020-01-01", warmup_bars=5)
        self.assertEqual(reason, "目标交易日前没有可用历史")


if __name__ == "__main__":
    unittest.main()
