from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from src.market.infrastructure.store import MarketStore, MarketError, normalize_code, to_sina_symbol


def _quotes(dates: list[str], base: float = 10.0) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "date": dates,
            "open": np.linspace(base, base + n * 0.1, n),
            "high": np.linspace(base + 0.5, base + 0.5 + n * 0.1, n),
            "low": np.linspace(base - 0.5, base - 0.5 + n * 0.1, n),
            "close": np.linspace(base + 0.2, base + 0.2 + n * 0.1, n),
            "volume": np.full(n, 1_000_000.0),
            "amount": np.full(n, 10_000_000.0),
            "outstanding_share": np.full(n, 1e9),
            "turnover": np.full(n, 0.001),
        }
    )


class IncrementalSyncTests(unittest.TestCase):
    """增量同步的跳过判据。判错就是每天静默地什么都不做。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "market.db"
        self.store = MarketStore(self.db)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def _sync(
        self,
        *,
        synced_on: str,
        stale_after_days: int | None = None,
        source: str = "",
    ) -> int:
        """把 watermark 的同步时间改成指定日期，再看会不会被跳过。"""
        from src.market.infrastructure.sync import sync_quotes

        self.store.set_watermark(
            "600519", last_trade_date="2026-03-01", status="ok", source=source
        )
        self.store.conn.execute(
            "UPDATE ingest_watermark SET last_synced_at = ? WHERE code = '600519'",
            (f"{synced_on}T10:00:00+08:00",),
        )
        self.store.conn.commit()

        calls: list[str] = []

        class Recorder:
            name = "recorder"

            def fetch_daily(self, code, *, instrument_type="STOCK"):
                calls.append(code)
                return _quotes(["2026-03-02"])

            def fetch_adjust_factors(self, code):
                return pd.DataFrame(columns=["date", "hfq_factor"])

        kwargs = {} if stale_after_days is None else {"stale_after_days": stale_after_days}
        sync_quotes(
            lambda: MarketStore(self.db), ["600519"],
            sources=[Recorder()], workers=1, min_interval=0.0,
            with_factors=False, with_today_spot=False, **kwargs,
        )
        return len(calls)

    def test_skips_only_what_was_synced_today(self) -> None:
        from datetime import date, timedelta

        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        self.assertEqual(self._sync(synced_on=today), 0, "今天同步过的应跳过")
        self.assertEqual(
            self._sync(synced_on=yesterday), 1,
            "昨天同步过的今天必须重新取——默认跳过它会让每日同步静默失效",
        )

    def test_spot_watermark_does_not_skip_the_daily_sync(self) -> None:
        """盘中 spot 推进的水位不算「今天同步过」。

        否则 10:30 看一眼行情台，当晚的历史同步就整只跳过，半天的盘中快照
        （成交量只有半天、最高最低还没走完）会作为当日定稿日 K 永久留在库里，
        而任务照常报 success。
        """
        from datetime import date

        today = date.today().isoformat()

        self.assertEqual(
            self._sync(synced_on=today, source="sina_spot"),
            1,
            "spot 水位不能让当日历史同步静默跳过",
        )

    def test_spot_row_does_not_hide_a_history_gap(self) -> None:
        """断档要按库内最后一根定稿日 K 算，不能按被 spot 推到今天的水位算。"""
        from datetime import date, timedelta
        from unittest import mock

        from src.market.infrastructure.sync import sync_quotes

        today = date.today()
        finalized = (today - timedelta(days=60)).isoformat()
        self.store.upsert_quotes(
            "600519", _quotes(["2020-01-02", finalized]), source="tencent"
        )
        # 盘中 spot 写了今天，并把水位一起推到今天。
        self.store.upsert_quotes(
            "600519", _quotes([today.isoformat()]), source="tencent_spot"
        )
        self.store.set_watermark(
            "600519",
            last_trade_date=today.isoformat(),
            status="ok",
            source="tencent_spot",
        )

        with mock.patch(
            "src.market.infrastructure.adapters.fetch_daily_routed",
            return_value=(_quotes([today.isoformat()]), "tencent"),
        ) as routed:
            sync_quotes(
                lambda: MarketStore(self.db),
                ["600519"],
                workers=1,
                min_interval=0.0,
                with_factors=False,
                with_today_spot=False,
            )

        routed.assert_called_once()
        self.assertEqual(routed.call_args.kwargs["recent_bars"], 65)

    def test_force_ignores_the_watermark(self) -> None:
        from datetime import date
        from src.market.infrastructure.sync import sync_quotes

        self.store.set_watermark("600519", status="ok")

        calls: list[str] = []

        class Recorder:
            name = "recorder"

            def fetch_daily(self, code, *, instrument_type="STOCK"):
                calls.append(code)
                return _quotes(["2026-03-02"])

            def fetch_adjust_factors(self, code):
                return pd.DataFrame(columns=["date", "hfq_factor"])

        sync_quotes(
            lambda: MarketStore(self.db), ["600519"], sources=[Recorder()],
            workers=1, min_interval=0.0, force=True, with_factors=False,
            with_today_spot=False,
        )
        self.assertEqual(len(calls), 1)


class TodaySpotTests(unittest.TestCase):
    """历史日 K 不含当日时，用实时行情补齐。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "market.db"
        self.store = MarketStore(self.db)
        self.store.upsert_quotes(
            "600519",
            _quotes(["2026-07-22", "2026-07-23", "2026-07-24"]),
            source="hist",
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_apply_today_spot_appends_realtime_bar(self) -> None:
        from datetime import date
        from unittest.mock import patch

        from src.market.infrastructure.sync import apply_today_spot

        today = date.today()
        # 模拟交易时段：日历里先有今天（非交易日会被 apply_today_spot 钳制跳过）
        self.store.upsert_quotes(
            "600519",
            _quotes([today.isoformat()], base=10.0),
            source="hist",
        )
        fake = pd.DataFrame(
            [
                {
                    "code": "600519",
                    "date": today,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "volume": 1_000_000.0,
                    "amount": 10_000_000.0,
                }
            ]
        )
        with patch(
            "src.market.infrastructure.adapters.fetch_spot_routed",
            return_value=(fake, "sina"),
        ):
            written = apply_today_spot(self.store, ["600519"])

        self.assertEqual(written, 1)
        self.assertEqual(self.store.coverage()["last_date"], today.isoformat())
        history = self.store.history("600519", adjust="none")
        last = history.iloc[-1]
        self.assertEqual(str(last["trade_date"]), today.isoformat())
        self.assertAlmostEqual(float(last["close"]), 10.5)
        # 换手率沿用上一交易日流通股本；优先成交额/(价×股本)。
        self.assertAlmostEqual(float(last["turnover"]), 10_000_000.0 / (10.5 * 1e9))
        mark = self.store.watermark("600519")
        self.assertEqual(mark["last_trade_date"], today.isoformat())
        self.assertEqual(mark["source"], "sina_spot")

    def test_apply_today_spot_reuses_live_quotes_without_fetching_again(self) -> None:
        from datetime import date
        from unittest.mock import patch

        from src.market.infrastructure.sync import apply_today_spot

        today = date.today()
        self.store.upsert_quotes(
            "600519",
            _quotes([today.isoformat()], base=10.0),
            source="hist",
        )
        with patch(
            "src.market.infrastructure.adapters.fetch_spot_routed",
            side_effect=AssertionError("live board must not fetch spot twice"),
        ):
            written = apply_today_spot(
                self.store,
                ["600519"],
                live_quotes=[
                    {
                        "code": "600519",
                        "price": 10.5,
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.5,
                        "volume": 1_000_000.0,
                        "amount": 10_000_000.0,
                        "trade_date": today.isoformat(),
                    }
                ],
            )

        self.assertEqual(written, 1)
        self.assertAlmostEqual(
            float(self.store.history("600519", adjust="none").iloc[-1]["close"]),
            10.5,
        )

    def test_apply_today_spot_uses_shares_before_today_even_if_today_exists(self) -> None:
        """coverage.last_date 已是今天（无股本）时，仍须用更早交易日的股本估换手。"""
        from datetime import date, timedelta
        from unittest.mock import patch

        from src.market.infrastructure.sync import apply_today_spot

        today = date.today()
        yesterday = (today - timedelta(days=1)).isoformat()
        today_s = today.isoformat()
        # 昨天有股本；今天已被无股本源写入 → 旧逻辑会查今天得到空 map。
        self.store.upsert_quotes(
            "600519",
            pd.DataFrame(
                [
                    {
                        "date": yesterday,
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.5,
                        "volume": 1_000_000.0,
                        "amount": 10_000_000.0,
                        "outstanding_share": 2e9,
                        "turnover": 0.0005,
                    },
                    {
                        "date": today_s,
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.2,
                        "volume": 500_000.0,
                        "amount": 5_000_000.0,
                        "outstanding_share": None,
                        "turnover": None,
                    },
                ]
            ),
            source="tencent",
        )
        fake = pd.DataFrame(
            [
                {
                    "code": "600519",
                    "date": today,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.8,
                    "volume": 4_000_000.0,
                    "amount": 40_000_000.0,
                }
            ]
        )
        with patch(
            "src.market.infrastructure.adapters.fetch_spot_routed",
            return_value=(fake, "sina"),
        ):
            written = apply_today_spot(self.store, ["600519"])
        self.assertEqual(written, 1)
        last = self.store.history("600519", adjust="none").iloc[-1]
        self.assertEqual(str(last["trade_date"]), today_s)
        self.assertAlmostEqual(float(last["close"]), 10.8)
        self.assertAlmostEqual(float(last["outstanding_share"]), 2e9)
        self.assertAlmostEqual(float(last["turnover"]), 40_000_000.0 / (10.8 * 2e9))

    def test_parallel_same_market_refresh_is_single_flight(self) -> None:
        from concurrent.futures import ThreadPoolExecutor
        from datetime import date
        import threading
        import time
        from unittest.mock import patch

        from src.market.infrastructure.sync import apply_today_spot

        today = date.today().isoformat()
        self.store.upsert_quotes("600519", _quotes([today], base=10.0), source="hist")
        fake = pd.DataFrame(
            [
                {
                    "code": "600519",
                    "date": today,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "volume": 1_000_000.0,
                    "amount": 10_500_000.0,
                }
            ]
        )
        calls = 0
        calls_lock = threading.Lock()

        def fetch(*_args, **_kwargs):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.08)
            return fake.copy(), "sina"

        def refresh() -> int:
            store = MarketStore(self.db)
            try:
                return apply_today_spot(store, ["600519"])
            finally:
                store.close()

        with patch(
            "src.market.infrastructure.adapters.fetch_spot_routed",
            side_effect=fetch,
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _item: refresh(), range(2)))

        self.assertEqual(results, [1, 1])
        self.assertEqual(calls, 1)

    def test_live_quote_without_a_date_is_not_stamped_today(self) -> None:
        """来源没给日期就不能盖上今天。

        节假日轮询行情台时，源回的是上一交易日的静态快照；盖成今天等于
        凭空造一个交易日（``trading_calendar`` 也会跟着长出来），此后
        ``shift_trading_days`` 算的 T+N 收益全是错的。
        """
        from datetime import date
        from unittest.mock import patch

        from src.market.infrastructure.sync import apply_today_spot

        today = date.today().isoformat()
        self.store.upsert_quotes("600519", _quotes([today], base=10.0), source="hist")
        before = self.store.history("600519", adjust="none").iloc[-1]["close"]

        with patch(
            "src.market.infrastructure.adapters.fetch_spot_routed",
            side_effect=AssertionError("live 通道不应再拉 spot"),
        ):
            written = apply_today_spot(
                self.store,
                ["600519"],
                live_quotes=[
                    {
                        "code": "600519",
                        "price": 99.0,
                        "open": 99.0,
                        "high": 99.0,
                        "low": 99.0,
                        "volume": 1_000_000.0,
                        "amount": 99_000_000.0,
                    }
                ],
            )

        self.assertEqual(written, 0)
        after = self.store.history("600519", adjust="none").iloc[-1]
        self.assertEqual(str(after["trade_date"]), today)
        self.assertAlmostEqual(float(after["close"]), float(before))

    def test_spot_single_flight_releases_waiters_when_owner_dies(self) -> None:
        """owner 被 BaseException（关站 / Ctrl-C）打断时也要放行等待者。

        single-flight 的 follower 是无超时 ``event.wait()``；owner 少设一次
        event，follower 就永远挂在 FastAPI 线程池里，行情台整片转圈。
        """
        from datetime import date
        import threading
        from unittest.mock import patch

        today = date.today().isoformat()
        self.store.upsert_quotes("600519", _quotes([today], base=10.0), source="hist")
        started = threading.Event()
        release = threading.Event()

        def killed(*_args, **_kwargs):
            started.set()
            release.wait(2.0)
            raise KeyboardInterrupt("shutdown")

        def refresh() -> None:
            store = MarketStore(self.db)
            try:
                apply_today_spot(store, ["600519"])
            except BaseException:  # noqa: BLE001 - 本测试只关心不挂死
                pass
            finally:
                store.close()

        from src.market.infrastructure.sync import apply_today_spot

        with patch(
            "src.market.infrastructure.adapters.fetch_spot_routed", side_effect=killed
        ):
            # daemon：修复前 follower 会永久挂住，非守护线程会连带吊死整个 pytest。
            owner = threading.Thread(target=refresh, name="spot-owner", daemon=True)
            owner.start()
            self.assertTrue(started.wait(3.0), "owner 未进入拉取")
            follower = threading.Thread(
                target=refresh, name="spot-follower", daemon=True
            )
            follower.start()
            time.sleep(0.2)  # 让 follower 先挂到同一个 flight 上
            release.set()
            follower.join(5.0)
            owner.join(5.0)

        self.assertFalse(follower.is_alive(), "owner 异常退出后 follower 仍在等待")

    def test_spot_persist_retries_on_database_locked(self) -> None:
        """spot 写库遇 locked 时有限退避，成功后不把 OperationalError 抛给用户。"""
        from datetime import date
        import sqlite3
        from unittest.mock import patch

        from src.market.infrastructure.sync import apply_today_spot
        from src.market.infrastructure import sync_spot as spot_mod

        today = date.today().isoformat()
        self.store.upsert_quotes("600519", _quotes([today], base=10.0), source="hist")
        fake = pd.DataFrame(
            [
                {
                    "code": "600519",
                    "date": today,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "volume": 1_000_000.0,
                    "amount": 10_500_000.0,
                }
            ]
        )
        calls = {"n": 0}
        real_persist = self.store.persist_quote_bar_receipts

        def flaky_persist(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise sqlite3.OperationalError("database is locked")
            return real_persist(*args, **kwargs)

        with (
            patch(
                "src.market.infrastructure.adapters.fetch_spot_routed",
                return_value=(fake, "sina"),
            ),
            patch.object(self.store, "persist_quote_bar_receipts", flaky_persist),
            patch.object(spot_mod, "_SPOT_WRITE_RETRY_DELAYS", (0.01, 0.01, 0.01)),
        ):
            written = apply_today_spot(self.store, ["600519"], raise_on_failure=True)

        self.assertEqual(written, 1)
        self.assertGreaterEqual(calls["n"], 3)

    def test_spot_lock_error_is_human_chinese(self) -> None:
        from datetime import date
        import sqlite3
        from unittest.mock import patch

        from src.market.infrastructure.adapters.base import AdapterError
        from src.market.infrastructure.sync import apply_today_spot
        from src.market.infrastructure import sync_spot as spot_mod

        today = date.today().isoformat()
        self.store.upsert_quotes("600519", _quotes([today], base=10.0), source="hist")
        fake = pd.DataFrame(
            [
                {
                    "code": "600519",
                    "date": today,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "volume": 1_000_000.0,
                    "amount": 10_500_000.0,
                }
            ]
        )

        with (
            patch(
                "src.market.infrastructure.adapters.fetch_spot_routed",
                return_value=(fake, "sina"),
            ),
            patch.object(
                self.store,
                "persist_quote_bar_receipts",
                side_effect=sqlite3.OperationalError("database is locked"),
            ),
            patch.object(spot_mod, "_SPOT_WRITE_RETRY_DELAYS", (0.01,)),
        ):
            with self.assertRaises(AdapterError) as ctx:
                apply_today_spot(self.store, ["600519"], raise_on_failure=True)

        msg = str(ctx.exception)
        self.assertIn("行情库正忙", msg)
        self.assertNotIn("OperationalError", msg)
        self.assertNotIn("database is locked", msg)

    def test_strict_refresh_rejects_stale_spot_date(self) -> None:
        from datetime import date, timedelta
        from unittest.mock import patch

        from src.market.infrastructure.adapters.base import AdapterError
        from src.market.infrastructure.sync import apply_today_spot

        today = date.today().isoformat()
        stale = (date.today() - timedelta(days=1)).isoformat()
        self.store.upsert_quotes("600519", _quotes([today], base=10.0), source="hist")
        fake = pd.DataFrame(
            [
                {
                    "code": "600519",
                    "date": stale,
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.5,
                    "close": 10.2,
                    "volume": 1_000_000.0,
                    "amount": 10_200_000.0,
                }
            ]
        )
        with patch(
            "src.market.infrastructure.adapters.fetch_spot_routed",
            return_value=(fake, "sina"),
        ):
            with self.assertRaises(AdapterError):
                apply_today_spot(self.store, ["600519"], raise_on_failure=True)

    def test_backfill_infers_shares_from_prior_turnover(self) -> None:
        """无股本列但有历史换手时，用 amount/(close*turnover) 反推股本再回填。"""
        from src.market.infrastructure.turnover_repair import backfill_missing_turnover

        self.store.upsert_quotes(
            "000001",
            pd.DataFrame(
                [
                    {
                        "date": "2026-07-27",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.5,
                        # 东财「手」：1e4 手 = 1e6 股；amount 按股×价，反推股本须用额而非手。
                        "volume": 10_000.0,
                        "amount": 10_500_000.0,
                        "outstanding_share": None,
                        "turnover": 0.02,  # 隐含股本 5e7
                    },
                    {
                        "date": "2026-07-28",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.6,
                        "volume": 2_000_000.0,
                        "amount": 20_000_000.0,
                        "outstanding_share": None,
                        "turnover": None,
                    },
                ]
            ),
            source="eastmoney",
        )
        report = backfill_missing_turnover(self.store, trade_dates=["2026-07-28"])
        self.assertEqual(report["updated"], 1)
        row = self.store.history("000001", adjust="none").iloc[-1]
        self.assertAlmostEqual(float(row["outstanding_share"]), 5e7)
        self.assertAlmostEqual(
            float(row["turnover"]),
            20_000_000.0 / (10.6 * 5e7),
        )

    def test_repair_inflated_turnover_clears_spot_and_rescales_lots(self) -> None:
        """东财手量 + spot 错股本 → repair 后换手回到正常小数。"""
        from src.market.infrastructure.turnover_repair import repair_inflated_turnover

        self.store.upsert_quotes(
            "001376",
            pd.DataFrame(
                [
                    {
                        "date": "2026-07-27",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.14,
                        "volume": 120_633.0,  # 手
                        "amount": 120_466_899.05,
                        "outstanding_share": None,
                        "turnover": 0.0564,
                    },
                    {
                        "date": "2026-07-30",
                        "open": 11.13,
                        "high": 11.45,
                        "low": 11.13,
                        "close": 11.15,
                        "volume": 34_086_464.0,  # 股（sina_spot）
                        "amount": 384_679_316.24,
                        # 误用 手/换手 反推的股本（约小 100 倍）
                        "outstanding_share": 2_138_882.9787234045,
                        "turnover": 15.9365726592226,
                    },
                ]
            ),
            source="eastmoney",
        )
        # 覆盖来源标记：第二日是 spot
        self.store.conn.execute(
            "UPDATE quotes_daily SET source='sina_spot' WHERE code=? AND trade_date=?",
            ("001376", "2026-07-30"),
        )
        self.store.conn.commit()

        report = repair_inflated_turnover(self.store, since="2026-07-28")
        self.assertGreaterEqual(report["cleared"], 1)
        self.assertGreaterEqual(report["updated"], 1)

        # 7.27 仍在 since 之前，手量不必改；回填靠成交额反推股本。
        hist = self.store.history("001376", adjust="none")
        day30 = hist[hist["trade_date"].astype(str) == "2026-07-30"].iloc[0]
        shares = float(day30["outstanding_share"])
        turnover = float(day30["turnover"])
        self.assertGreater(shares, 1e8)
        self.assertLess(turnover, 0.5)
        self.assertAlmostEqual(
            turnover,
            384_679_316.24 / (11.15 * shares),
            places=5,
        )

    def test_backfill_missing_turnover_walks_past_empty_share_days(self) -> None:
        """中间交易日股本全空时，回填须跳到更早仍有股本的日子。"""
        from src.market.infrastructure.turnover_repair import backfill_missing_turnover

        self.store.upsert_quotes(
            "600519",
            pd.DataFrame(
                [
                    {
                        "date": "2026-07-27",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.5,
                        "volume": 1_000_000.0,
                        "amount": 10_000_000.0,
                        "outstanding_share": 5e8,
                        "turnover": 0.002,
                    },
                    {
                        "date": "2026-07-28",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.6,
                        "volume": 2_500_000.0,
                        "amount": 25_000_000.0,
                        "outstanding_share": None,
                        "turnover": None,
                    },
                    {
                        "date": "2026-07-29",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.7,
                        "volume": 5_000_000.0,
                        "amount": 50_000_000.0,
                        "outstanding_share": None,
                        "turnover": None,
                    },
                ]
            ),
            source="sina_spot",
        )
        report = backfill_missing_turnover(self.store)
        self.assertEqual(report["updated"], 2)
        hist = self.store.history("600519", adjust="none").set_index("trade_date")
        self.assertAlmostEqual(float(hist.loc["2026-07-28", "outstanding_share"]), 5e8)
        self.assertAlmostEqual(
            float(hist.loc["2026-07-28", "turnover"]),
            25_000_000.0 / (10.6 * 5e8),
        )
        self.assertAlmostEqual(float(hist.loc["2026-07-29", "outstanding_share"]), 5e8)
        self.assertAlmostEqual(
            float(hist.loc["2026-07-29", "turnover"]),
            50_000_000.0 / (10.7 * 5e8),
        )


if __name__ == "__main__":
    unittest.main()
