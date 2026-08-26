"""日线多源竞速与合并口径。

现货路由 / 粘性线路用例在 `test_adapters_sticky.py`；假适配器在 `adapter_fakes.py`。
"""
from __future__ import annotations

import time
import unittest

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError
from src.market.infrastructure.adapters.registry import reset_registry
from src.market.infrastructure.adapters.router import fetch_daily_best

from tests.market.adapter_fakes import _FakeAdapter, _daily_frame


class FetchDailyBestTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_registry()

    def test_primary_follows_preferred_order_not_rtt(self) -> None:
        """协作合并：主源取 preferred_order 中首个有贡献者，不是谁快谁赢。"""
        reset_registry(
            [
                _FakeAdapter("slow", delay=0.12, frame=_daily_frame(2)),
                _FakeAdapter("fast", delay=0.02, frame=_daily_frame(5)),
            ]
        )
        frame, winner = fetch_daily_best("600519", max_workers=2)
        self.assertEqual(winner, "slow")
        # slow 优先覆盖冲突日；fast 可补缺失日 → 行数 ≥ slow
        self.assertGreaterEqual(len(frame), 2)

    def test_merge_waits_for_all_sources(self) -> None:
        """协作合并须等齐各源，不再提前取消慢源。"""
        reset_registry(
            [
                _FakeAdapter("slow", delay=0.35, frame=_daily_frame(2)),
                _FakeAdapter("fast", delay=0.02, frame=_daily_frame(5)),
            ]
        )
        started = time.perf_counter()
        frame, winner = fetch_daily_best("600519", max_workers=2)
        elapsed = time.perf_counter() - started

        self.assertEqual(winner, "slow")
        self.assertGreaterEqual(len(frame), 2)
        self.assertGreaterEqual(elapsed, 0.30)

    def test_all_fail_raises(self) -> None:
        reset_registry(
            [
                _FakeAdapter("a", fail=True),
                _FakeAdapter("b", fail=True),
            ]
        )
        with self.assertRaises(AdapterError) as ctx:
            fetch_daily_best("600519")
        self.assertIn("全部 hist_daily", str(ctx.exception))

    def test_cancelled_queued_adapter_releases_request_gate(self) -> None:
        queued = [
            _FakeAdapter(f"queued_gate_{index}", delay=0.2, frame=_daily_frame(1))
            for index in range(5)
        ]
        fast = _FakeAdapter("fast_gate", frame=_daily_frame(2))
        reset_registry([fast, *queued])

        frame, winner = fetch_daily_best(
            "600519",
            adapter_ids=[fast.meta.id, *(adapter.meta.id for adapter in queued)],
            max_workers=1,
        )
        self.assertEqual(winner, fast.meta.id)
        self.assertEqual(len(frame), 2)

        # 线程池只能启动第一个 queued，其余 future 会在获胜后取消；被取消的
        # adapter 仍必须能在后续请求中重新获得 gate。
        frame, winner = fetch_daily_best(
            "600519", adapter_ids=[queued[-1].meta.id], max_workers=1
        )
        self.assertEqual(winner, queued[-1].meta.id)
        self.assertEqual(len(frame), 1)


def _one_bar(
    *,
    date: str = "2026-01-05",
    open_: float = 10.0,
    high: float = 11.0,
    low: float = 9.0,
    close: float = 10.5,
    volume: float = 1_000_000.0,
    amount: float = 10_500_000.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": date,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
            }
        ]
    )


class DailyMergeTests(unittest.TestCase):
    """互补合并的冲突口径：坏值 / 估算值不许压过真实行情。"""

    def tearDown(self) -> None:
        reset_registry()

    def test_zero_price_row_loses_to_a_source_with_real_quotes(self) -> None:
        """0 元 OHLC 是源侧缺失哨兵，不是行情；它不能因为排在前面就赢。"""
        from src.market.infrastructure.adapters.daily_merge import merge_daily_frames

        broken = _one_bar(open_=0.0, high=0.0, low=0.0, close=0.0, volume=0.0, amount=0.0)
        good = _one_bar()

        merged, primary, _contributed = merge_daily_frames(
            [("broken", broken), ("good", good)],
            preferred_order=["broken", "good"],
        )

        row = merged.iloc[0]
        self.assertAlmostEqual(float(row["close"]), 10.5)
        self.assertAlmostEqual(float(row["open"]), 10.0)
        self.assertAlmostEqual(float(row["volume"]), 1_000_000.0)
        self.assertEqual(primary, "good")

    def test_nan_close_row_loses_to_a_source_with_real_quotes(self) -> None:
        from src.market.infrastructure.adapters.daily_merge import merge_daily_frames

        broken = _one_bar(close=float("nan"))
        good = _one_bar(close=10.5)

        merged, _primary, _contributed = merge_daily_frames(
            [("broken", broken), ("good", good)],
            preferred_order=["broken", "good"],
        )

        self.assertAlmostEqual(float(merged.iloc[0]["close"]), 10.5)

    def test_zero_amount_is_filled_from_a_source_that_has_one(self) -> None:
        """有的源缺字段时填 0（悟道 kline 就是 ``float(x or 0)``），0 不是成交额。"""
        from src.market.infrastructure.adapters.daily_merge import merge_daily_frames

        blank = _one_bar(volume=0.0, amount=0.0)
        real = _one_bar(volume=1_000_000.0, amount=10_500_000.0)

        merged, _primary, _contributed = merge_daily_frames(
            [("blank", blank), ("real", real)],
            preferred_order=["blank", "real"],
        )

        row = merged.iloc[0]
        self.assertAlmostEqual(float(row["amount"]), 10_500_000.0)
        self.assertAlmostEqual(float(row["volume"]), 1_000_000.0)

    def test_preferred_real_quote_still_wins_over_a_later_source(self) -> None:
        from src.market.infrastructure.adapters.daily_merge import merge_daily_frames

        first = _one_bar(close=10.5)
        second = _one_bar(close=99.0)

        merged, primary, _contributed = merge_daily_frames(
            [("first", first), ("second", second)],
            preferred_order=["first", "second"],
        )

        self.assertAlmostEqual(float(merged.iloc[0]["close"]), 10.5)
        self.assertEqual(primary, "first")

    def test_estimated_amount_loses_to_a_real_amount(self) -> None:
        """腾讯日 K 的成交额是 close×volume 估的，不能盖掉源生成交额。"""
        from src.market.infrastructure.adapters.daily_merge import merge_daily_frames

        estimated = _one_bar(amount=10.5 * 1_000_000.0)
        real = _one_bar(amount=9_900_000.0)

        merged, _primary, _contributed = merge_daily_frames(
            [("tencent", estimated), ("eastmoney", real)],
            preferred_order=["tencent", "eastmoney"],
            estimated_fields={"tencent": ("amount",)},
        )

        row = merged.iloc[0]
        self.assertAlmostEqual(float(row["amount"]), 9_900_000.0)
        # 只有被声明为估算的列让位，价量仍按优先序
        self.assertAlmostEqual(float(row["close"]), 10.5)

    def test_estimated_amount_is_kept_when_nobody_else_has_one(self) -> None:
        from src.market.infrastructure.adapters.daily_merge import merge_daily_frames

        estimated = _one_bar(amount=10.5 * 1_000_000.0)

        merged, _primary, _contributed = merge_daily_frames(
            [("tencent", estimated)],
            preferred_order=["tencent"],
            estimated_fields={"tencent": ("amount",)},
        )

        self.assertAlmostEqual(float(merged.iloc[0]["amount"]), 10.5 * 1_000_000.0)

    def test_router_lets_a_real_amount_beat_the_estimating_source(self) -> None:
        estimating = _FakeAdapter(
            "estimator",
            frame=_one_bar(amount=10.5 * 1_000_000.0),
            estimated_fields=("amount",),
        )
        exact = _FakeAdapter("exact", frame=_one_bar(amount=9_900_000.0))
        reset_registry([estimating, exact])

        frame, winner = fetch_daily_best("600519", max_workers=2)

        self.assertEqual(winner, "estimator")
        self.assertAlmostEqual(float(frame.iloc[0]["amount"]), 9_900_000.0)
