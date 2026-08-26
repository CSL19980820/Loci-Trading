"""读写双库：screen_run 选股读热库，requires_full_history 回退全量库。"""
from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.market import MarketStore, mirror_to_hot
from src.strategy.application.screen_run import (
    execute_screen_run,
    screen_run_snapshot,
    screen_run_update,
)

_QUOTES_COLUMNS = (
    "trade_date, code, open, high, low, close, volume, amount, "
    "outstanding_share, turnover, source, receipt_id, fetched_at"
)


def _insert_instrument(store: MarketStore, code: str, name: str) -> None:
    store.upsert_instruments(
        [{"code": code, "name": name, "market": "SZ", "instrument_type": "STOCK"}]
    )


def _insert_quote(store: MarketStore, trade_date: str, code: str) -> None:
    store.conn.execute(
        f"INSERT INTO quotes_daily({_QUOTES_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            trade_date, code, 10.0, 10.5, 9.8, 10.2, 1000, 10000,
            None, None, "test", None, f"{trade_date}T00:00:00",
        ),
    )
    store.conn.execute(
        "INSERT INTO trading_calendar(trade_date, updated_at) VALUES(?, datetime('now'))"
        " ON CONFLICT(trade_date) DO NOTHING",
        (trade_date,),
    )
    store.conn.commit()


def _seed(store: MarketStore, codes: list[str], days: list[str]) -> None:
    for code in codes:
        _insert_instrument(store, code, f"票{code}")
    for day in days:
        for code in codes:
            _insert_quote(store, day, code)


def _fake_result(trade_date: str, db_path: str) -> SimpleNamespace:
    return SimpleNamespace(
        strategy_slug="demo",
        strategy_revision="rev1",
        trade_date=trade_date,
        entry_timing="next_open",
        universe_size=2,
        elapsed_seconds=0.01,
        params={},
        effective_params={},
        picks=[{"code": "000001", "factors": {"score": 90.0}}],
        health=None,
        universe={},
        universe_funnel={},
        data_snapshot={},
        recorded_db=db_path,
    )


class ScreenRunHotStoreTests(unittest.TestCase):
    """execute_screen_run 的读写双库：选股读热库、写仍走全量、回退语义。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.full_path = root / "market.db"
        self.hot_path = root / "market_hot.db"
        screen_run_update(status="idle", result=None, error="", log=[])

    def tearDown(self) -> None:
        screen_run_update(status="idle", result=None, error="", log=[])
        self.temp.cleanup()

    def _run(
        self,
        *,
        full_seeded: bool,
        hot_prepopulated: bool,
        engine: SimpleNamespace,
        wipe_full_quotes: bool = False,
    ) -> dict[str, object]:
        full = MarketStore(self.full_path)
        hot = MarketStore(self.hot_path)
        try:
            if full_seeded:
                _seed(full, ["000001", "600519"], ["2026-07-30", "2026-07-31"])
            if hot_prepopulated:
                mirror_to_hot(full, hot)
            if wipe_full_quotes:
                # 全量库删行情（保留日历/instruments），模拟「全量无数据、热库有数据」
                full.conn.execute("DELETE FROM quotes_daily")
                full.conn.commit()

            captured: dict[str, object] = {}
            mirror_calls: list[tuple[object, object]] = []

            def fake_screen(store, _slug, **_kwargs) -> SimpleNamespace:
                captured["db_path"] = str(store.db_path)
                return _fake_result("2026-07-31", str(store.db_path))

            def fake_mirror(full_store, hot_store, **_kwargs) -> dict[str, object]:
                mirror_calls.append((full_store, hot_store))
                return {"mode": "incremental", "quotes": 0, "end": "2026-07-31"}

            with (
                patch("src.strategy.get", lambda _slug: engine),
                patch("src.strategy.screen", side_effect=fake_screen),
                patch("src.market.mirror_recent_to_hot", side_effect=fake_mirror),
            ):
                execute_screen_run(
                    {
                        "strategy": "demo",
                        "start": "2026-07-30",
                        "end": "2026-07-31",
                        "record_candidates": False,
                        "skip_health_check": True,
                    },
                    market_factory=lambda: MarketStore(self.full_path),
                    palace_db=None,
                    hot_db=str(self.hot_path),
                )
            captured["mirror_calls"] = len(mirror_calls)
            captured["status"] = screen_run_snapshot()["status"]
            return captured
        finally:
            full.close()
            hot.close()

    def test_screen_reads_hot_store_when_full_has_no_data(self) -> None:
        """热库有数据、全量无数据时选股仍正确：读连接必须指向热库。"""
        captured = self._run(
            full_seeded=True,
            hot_prepopulated=True,
            engine=SimpleNamespace(requires_full_history=False),
            wipe_full_quotes=True,
        )
        self.assertEqual(captured["status"], "done")
        self.assertEqual(captured["db_path"], str(self.hot_path))
        # 镜像步骤已执行（增量镜像在选股读热库之前）
        self.assertEqual(captured["mirror_calls"], 1)

    def test_requires_full_history_falls_back_to_full_store(self) -> None:
        """requires_full_history=True 的策略回退全量库，且不做热库镜像。"""
        captured = self._run(
            full_seeded=True,
            hot_prepopulated=True,
            engine=SimpleNamespace(requires_full_history=True),
        )
        self.assertEqual(captured["status"], "done")
        self.assertEqual(captured["db_path"], str(self.full_path))
        self.assertEqual(captured["mirror_calls"], 0)

    def test_hot_db_absent_uses_full_store(self) -> None:
        """未传 hot_db 时行为不变：选股仍走全量库（兼容旧调用方）。"""
        full = MarketStore(self.full_path)
        try:
            _seed(full, ["000001", "600519"], ["2026-07-30", "2026-07-31"])
            captured: dict[str, object] = {}

            def fake_screen(store, _slug, **_kwargs) -> SimpleNamespace:
                captured["db_path"] = str(store.db_path)
                return _fake_result("2026-07-31", str(store.db_path))

            with (
                patch("src.strategy.get", lambda _slug: SimpleNamespace(requires_full_history=False)),
                patch("src.strategy.screen", side_effect=fake_screen),
            ):
                execute_screen_run(
                    {
                        "strategy": "demo",
                        "start": "2026-07-30",
                        "end": "2026-07-31",
                        "record_candidates": False,
                        "skip_health_check": True,
                    },
                    market_factory=lambda: MarketStore(self.full_path),
                    palace_db=None,
                )
            self.assertEqual(screen_run_snapshot()["status"], "done")
            self.assertEqual(captured["db_path"], str(self.full_path))
        finally:
            full.close()

    def test_mirror_failure_falls_back_to_full_store(self) -> None:
        """镜像失败时回退全量库选股（与 job:screen 语义一致）。"""
        full = MarketStore(self.full_path)
        hot = MarketStore(self.hot_path)
        try:
            _seed(full, ["000001", "600519"], ["2026-07-30", "2026-07-31"])
            mirror_to_hot(full, hot)
            captured: dict[str, object] = {}

            def fake_screen(store, _slug, **_kwargs) -> SimpleNamespace:
                captured["db_path"] = str(store.db_path)
                return _fake_result("2026-07-31", str(store.db_path))

            with (
                patch(
                    "src.strategy.get",
                    lambda _slug: SimpleNamespace(requires_full_history=False),
                ),
                patch("src.strategy.screen", side_effect=fake_screen),
                patch(
                    "src.market.mirror_recent_to_hot",
                    side_effect=RuntimeError("hot db busy"),
                ),
            ):
                execute_screen_run(
                    {
                        "strategy": "demo",
                        "start": "2026-07-30",
                        "end": "2026-07-31",
                        "record_candidates": False,
                        "skip_health_check": True,
                    },
                    market_factory=lambda: MarketStore(self.full_path),
                    palace_db=None,
                    hot_db=str(self.hot_path),
                )
            self.assertEqual(screen_run_snapshot()["status"], "done")
            self.assertEqual(captured["db_path"], str(self.full_path))
            log = screen_run_snapshot().get("log") or []
            self.assertTrue(
                any("回退全量库" in str(line) for line in log),
                f"expected fallback log, got {log!r}",
            )
        finally:
            full.close()
            hot.close()


class MarketHotStoreFactoryTests(unittest.TestCase):
    def test_quant_common_factory_opens_hot_store(self) -> None:
        """quant_common.market_hot_store 打开热库（schema 与 MarketStore 一致）。"""
        from src.shared.api_deps import market_hot_store

        with tempfile.TemporaryDirectory() as tmp:
            hot_path = str(Path(tmp) / "market_hot.db")
            store = market_hot_store(hot_path)
            try:
                self.assertIsInstance(store, MarketStore)
                self.assertEqual(str(store.db_path), hot_path)
                # 完整 schema：可以正常读写日 K（与全量 MarketStore 同接口）
                _seed(store, ["000001"], ["2026-07-31"])
                self.assertGreater(len(store.trading_days()), 0)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()