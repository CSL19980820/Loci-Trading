"""腾讯日 K 成交量单位：科创板返回「股」，其余板块返回「手」。

实测 2026-08：688/689 若按手 ×100，隐含换手率会到 170%~290%（物理不可能）。
该源的 amount 由 close*volume 合成，所以 amount/(volume*close) 恒为 1，
`scale_lot_volumes` 的比值判据识别不出这类膨胀，只能靠板块 + 换手率判据。
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from src.market.infrastructure import tencent
from src.market.infrastructure.store import MarketStore
from src.market.infrastructure.turnover_repair import rescale_star_daily_volumes


class DailyVolumeScaleTests(unittest.TestCase):
    def test_star_board_keeps_source_shares(self) -> None:
        self.assertEqual(tencent.daily_volume_scale("sh688008"), 1.0)
        self.assertEqual(tencent.daily_volume_scale("sh689009"), 1.0)

    def test_other_boards_convert_lots_to_shares(self) -> None:
        for symbol in ("sh600519", "sz300750", "sz000001", "bj920088"):
            self.assertEqual(tencent.daily_volume_scale(symbol), 100.0, symbol)

    def test_scale_accepts_bare_code(self) -> None:
        self.assertEqual(tencent.daily_volume_scale("688981"), 1.0)
        self.assertEqual(tencent.daily_volume_scale("600519"), 100.0)

    def test_parse_rows_applies_scale_to_volume_and_amount(self) -> None:
        raw = [["2026-08-11", "10.0", "12.0", "12.5", "9.5", "1000"]]
        star = tencent._parse_daily_rows(raw, volume_scale=1.0)
        main = tencent._parse_daily_rows(raw, volume_scale=100.0)
        self.assertEqual(float(star.iloc[0]["volume"]), 1_000.0)
        self.assertEqual(float(main.iloc[0]["volume"]), 100_000.0)
        # amount 由 close*volume 合成，必须跟着量一起缩放
        self.assertEqual(float(star.iloc[0]["amount"]), 12.0 * 1_000.0)
        self.assertEqual(float(main.iloc[0]["amount"]), 12.0 * 100_000.0)


class RescaleStarDailyVolumesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MarketStore(Path(self.temp.name) / "market.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def _seed(
        self,
        code: str,
        *,
        volume: float,
        source: str,
        dates: tuple[str, ...] = ("2026-08-10",),
        volumes: tuple[float, ...] | None = None,
    ) -> None:
        vols = volumes or tuple(volume for _ in dates)
        self.store.upsert_quotes(
            code,
            pd.DataFrame(
                [
                    {
                        "date": day,
                        "open": 100.0,
                        "high": 110.0,
                        "low": 95.0,
                        "close": 100.0,
                        "volume": vol,
                        "amount": vol * 100.0,
                        "outstanding_share": 1e9,
                        "turnover": None,
                    }
                    for day, vol in zip(dates, vols)
                ]
            ),
            source=source,
        )
        self.store.conn.execute(
            "UPDATE quotes_daily SET source=? WHERE code=?", (source, code)
        )
        self.store.conn.commit()

    def _row(self, code: str) -> pd.Series:
        return self.store.history(code, adjust="none").iloc[-1]

    def test_rescales_inflated_star_rows(self) -> None:
        # 24 亿股 / 10 亿流通股 = 240% 换手，不可能
        self._seed("688981", volume=2.4e9, source="tencent")

        report = rescale_star_daily_volumes(self.store)

        self.assertEqual(report["rescaled_rows"], 1)
        self.assertEqual(report["rescaled_codes"], 1)
        row = self._row("688981")
        self.assertAlmostEqual(float(row["volume"]), 2.4e7)
        self.assertAlmostEqual(float(row["amount"]), 2.4e9)

    def test_leaves_healthy_star_rows_alone(self) -> None:
        # 2.4% 换手，正常
        self._seed("688981", volume=2.4e7, source="tencent")

        report = rescale_star_daily_volumes(self.store)

        self.assertEqual(report["rescaled_rows"], 0)
        self.assertAlmostEqual(float(self._row("688981")["volume"]), 2.4e7)

    def test_leaves_non_star_boards_alone(self) -> None:
        """主板高换手可能是真的，不属本 bug 范围。"""
        self._seed("600519", volume=2.4e9, source="tencent")

        report = rescale_star_daily_volumes(self.store)

        self.assertEqual(report["rescaled_rows"], 0)
        self.assertAlmostEqual(float(self._row("600519")["volume"]), 2.4e9)

    def test_leaves_spot_source_alone(self) -> None:
        """现价接口各板块统一为「手」，不受该 bug 影响。"""
        self._seed("688981", volume=2.4e9, source="tencent_spot")

        report = rescale_star_daily_volumes(self.store)

        self.assertEqual(report["rescaled_rows"], 0)

    def test_is_idempotent(self) -> None:
        self._seed("688981", volume=2.4e9, source="tencent")

        first = rescale_star_daily_volumes(self.store)
        second = rescale_star_daily_volumes(self.store)

        self.assertEqual(first["rescaled_rows"], 1)
        self.assertEqual(second["rescaled_rows"], 0)
        self.assertAlmostEqual(float(self._row("688981")["volume"]), 2.4e7)

    def test_since_bounds_the_repair(self) -> None:
        self._seed("688981", volume=2.4e9, source="tencent")

        report = rescale_star_daily_volumes(self.store, since="2026-08-11")

        self.assertEqual(report["rescaled_rows"], 0)

    def test_also_fixes_quiet_days_of_an_affected_code(self) -> None:
        """判据是代码级的：安静日膨胀后仍不到 100% 换手，行级阈值会漏掉。"""
        self._seed(
            "688981",
            volume=0,
            source="tencent",
            dates=("2026-08-06", "2026-08-07", "2026-08-10"),
            # 0.2% 真实换手 → 膨胀后仅 20%，单看这一行判不出来
            volumes=(2.0e8, 2.4e9, 2.0e8),
        )

        report = rescale_star_daily_volumes(self.store)

        self.assertEqual(report["rescaled_rows"], 3)
        self.assertEqual(report["rescaled_codes"], 1)
        hist = self.store.history("688981", adjust="none")
        self.assertAlmostEqual(float(hist.iloc[0]["volume"]), 2.0e6)
        self.assertAlmostEqual(float(hist.iloc[1]["volume"]), 2.4e7)
        self.assertAlmostEqual(float(hist.iloc[2]["volume"]), 2.0e6)

    def test_detects_inflation_without_outstanding_share_via_spot(self) -> None:
        """689009 这类从未落过股本的票，只能拿自己的 spot 行当标尺。"""
        self.store.upsert_quotes(
            "689009",
            pd.DataFrame(
                [
                    {
                        "date": "2026-08-10",
                        "open": 100.0,
                        "high": 110.0,
                        "low": 95.0,
                        "close": 100.0,
                        "volume": 1.29e12,  # 被 ×100 的历史行
                        "amount": 1.29e14,
                        "outstanding_share": None,
                        "turnover": None,
                    }
                ]
            ),
            source="tencent",
        )
        self.store.upsert_quotes(
            "689009",
            pd.DataFrame(
                [
                    {
                        "date": "2026-08-11",
                        "open": 100.0,
                        "high": 110.0,
                        "low": 95.0,
                        "close": 100.0,
                        "volume": 3.28e7,  # spot 行是对的
                        "amount": 3.28e9,
                        "outstanding_share": None,
                        "turnover": None,
                    }
                ]
            ),
            source="tencent_spot",
        )

        report = rescale_star_daily_volumes(self.store)

        self.assertEqual(report["rescaled_rows"], 1)
        hist = self.store.history("689009", adjust="none")
        hist = hist[hist["trade_date"].astype(str) == "2026-08-10"]
        self.assertAlmostEqual(float(hist.iloc[0]["volume"]), 1.29e10)
        # spot 行不在修复范围内，必须原样保留
        spot = self.store.history("689009", adjust="none")
        spot = spot[spot["trade_date"].astype(str) == "2026-08-11"]
        self.assertAlmostEqual(float(spot.iloc[0]["volume"]), 3.28e7)

    def test_healthy_code_with_quiet_days_is_untouched(self) -> None:
        """整段都正常的代码不能因为某天换手低就被误缩。"""
        self._seed(
            "688981",
            volume=0,
            source="tencent",
            dates=("2026-08-06", "2026-08-10"),
            volumes=(2.0e6, 2.4e7),
        )

        report = rescale_star_daily_volumes(self.store)

        self.assertEqual(report["rescaled_rows"], 0)
        hist = self.store.history("688981", adjust="none")
        self.assertAlmostEqual(float(hist.iloc[0]["volume"]), 2.0e6)


if __name__ == "__main__":
    unittest.main()
