"""读写双库：热库重建 / 增量镜像 / 选股读热库 / 同步镜像失败不阻断。"""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.market import MarketStore
from src.market.infrastructure.store_hot import mirror_recent_to_hot
from src.ops.application.jobs.context import JobContext
from src.ops.application.jobs.hot_rebuild import execute_hot_rebuild
from src.ops.application.jobs.screen import execute_screen
from src.ops.application.jobs.sync import execute_sync

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


def _quote_count(store: MarketStore) -> int:
    return int(store.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0])


class HotRebuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.full_path = root / "market.db"
        self.hot_path = root / "market_hot.db"
        self.full = MarketStore(self.full_path)
        self.hot = MarketStore(self.hot_path)

    def tearDown(self) -> None:
        self.full.close()
        self.hot.close()
        self.temp.cleanup()

    def test_execute_hot_rebuild_window_and_instruments(self) -> None:
        codes = ["000001", "600519"]
        for code in codes:
            _insert_instrument(self.full, code, f"票{code}")
        dates = ["2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"]
        for day in dates:
            for code in codes:
                _insert_quote(self.full, day, code)

        ctx = JobContext(market_db=self.full_path, market_hot_db=self.hot_path)
        payload = execute_hot_rebuild({"window_trading_days": 2}, ctx)

        self.assertEqual(payload["mode"], "rebuild")
        # 窗口 2 个交易日 × 2 票；热库行数必须 ≤ 全量
        self.assertEqual(payload["quotes"], 4)
        self.assertEqual(payload["start"], "2026-07-30")
        self.assertEqual(payload["end"], "2026-07-31")
        self.assertEqual(payload["config"]["window_trading_days"], 2)
        self.assertLessEqual(_quote_count(self.hot), _quote_count(self.full))
        hot_codes = {item["code"] for item in self.hot.list_instruments(status="")}
        self.assertEqual(hot_codes, set(codes))

    def test_execute_hot_rebuild_defaults_window(self) -> None:
        _insert_instrument(self.full, "000001", "平安银行")
        _insert_quote(self.full, "2026-07-31", "000001")
        ctx = JobContext(market_db=self.full_path, market_hot_db=self.hot_path)
        payload = execute_hot_rebuild({}, ctx)
        self.assertEqual(payload["config"]["window_trading_days"], 700)
        self.assertEqual(payload["mode"], "rebuild")

    def test_mirror_recent_to_hot_includes_latest_trade_date(self) -> None:
        codes = ["000001", "600519"]
        for code in codes:
            _insert_instrument(self.full, code, f"票{code}")
        for day in ("2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"):
            for code in codes:
                _insert_quote(self.full, day, code)
        ctx = JobContext(market_db=self.full_path, market_hot_db=self.hot_path)
        execute_hot_rebuild({}, ctx)
        self.assertEqual(_quote_count(self.hot), 10)

        # 全量库再补一个最新交易日 → 增量镜像后热库必须含它
        for code in codes:
            _insert_quote(self.full, "2026-08-03", code)
        payload = mirror_recent_to_hot(self.full, self.hot)
        self.assertEqual(payload["mode"], "incremental")
        hot_dates = {
            row[0]
            for row in self.hot.conn.execute(
                "SELECT DISTINCT trade_date FROM quotes_daily"
            ).fetchall()
        }
        self.assertIn("2026-08-03", hot_dates)
        self.assertEqual(_quote_count(self.hot), 12)


class ScreenUsesHotStoreTests(unittest.TestCase):
    def test_execute_screen_reads_from_hot_store(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        full_path = root / "market.db"
        hot_path = root / "market_hot.db"
        full = MarketStore(full_path)
        hot = MarketStore(hot_path)
        try:
            for code in ("000001", "600519"):
                _insert_instrument(full, code, f"票{code}")
                _insert_quote(full, "2026-07-30", code)
                _insert_quote(full, "2026-07-31", code)
            execute_hot_rebuild(
                {}, JobContext(market_db=full_path, market_hot_db=hot_path)
            )

            captured: dict[str, object] = {}

            def fake_screen(store, _slug, **_kwargs):
                captured["db_path"] = str(store.db_path)
                return SimpleNamespace(
                    strategy_slug="demo",
                    strategy_revision="v1",
                    trade_date="2026-07-31",
                    universe_size=2,
                    entry_timing="close",
                    elapsed_seconds=0.1,
                    params={},
                    effective_params={},
                    universe=["000001", "600519"],
                    universe_funnel={"core": 2},
                    data_snapshot={"rows": 4, "window_days": 2},
                    picks=[{"code": "000001", "name": "平安银行", "score": 90}],
                )

            ctx = JobContext(market_db=full_path, market_hot_db=hot_path)
            with (
                patch(
                    "src.market.application.screen_spot.ensure_today_quotes_for_screen",
                    return_value={
                        "status": "refreshed",
                        "written": 2,
                        "coverage": {"listed": 2, "present": 2, "ratio": 1.0},
                    },
                ),
                patch("src.market.apply_today_spot", lambda *_a, **_k: 2),
                patch("src.strategy.get", lambda _slug: SimpleNamespace(name="演示")),
                patch("src.strategy.screen", fake_screen),
            ):
                payload = execute_screen(
                    {"strategy": "demo", "record_candidates": False}, ctx
                )
            # 选股必须走热库连接（与全量库写锁物理隔离）
            self.assertEqual(captured["db_path"], str(hot_path))
            self.assertEqual(payload["strategy"], "demo")
            self.assertEqual(payload["picks"][0]["code"], "000001")
        finally:
            full.close()
            hot.close()
            self.temp.cleanup()

    def _fake_screen_result(self, trade_date: str = "2026-07-31") -> SimpleNamespace:
        return SimpleNamespace(
            strategy_slug="demo",
            strategy_revision="v1",
            trade_date=trade_date,
            universe_size=2,
            entry_timing="close",
            elapsed_seconds=0.1,
            params={},
            effective_params={},
            universe=["000001", "600519"],
            universe_funnel={"core": 2},
            data_snapshot={"rows": 4, "window_days": 2},
            picks=[{"code": "000001", "name": "平安银行", "score": 90}],
        )

    def test_execute_screen_mirror_failure_falls_back_to_full(self) -> None:
        """镜像失败时回退全量库选股，不假装哨兵会修。"""
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        full_path = root / "market.db"
        hot_path = root / "market_hot.db"
        full = MarketStore(full_path)
        hot = MarketStore(hot_path)
        try:
            for code in ("000001", "600519"):
                _insert_instrument(full, code, f"票{code}")
                _insert_quote(full, "2026-07-30", code)
                _insert_quote(full, "2026-07-31", code)
            execute_hot_rebuild(
                {}, JobContext(market_db=full_path, market_hot_db=hot_path)
            )

            captured: dict[str, object] = {}

            def fake_screen(store, _slug, **_kwargs):
                captured["db_path"] = str(store.db_path)
                return self._fake_screen_result()

            ctx = JobContext(market_db=full_path, market_hot_db=hot_path)
            with (
                patch(
                    "src.market.application.screen_spot.ensure_today_quotes_for_screen",
                    return_value={
                        "status": "refreshed",
                        "written": 2,
                        "coverage": {"listed": 2, "present": 2, "ratio": 1.0},
                    },
                ),
                patch("src.market.apply_today_spot", lambda *_a, **_k: 2),
                patch("src.strategy.get", lambda _slug: SimpleNamespace(name="演示")),
                patch("src.strategy.screen", fake_screen),
                patch(
                    "src.market.mirror_recent_to_hot",
                    side_effect=RuntimeError("hot db busy"),
                ),
            ):
                payload = execute_screen(
                    {"strategy": "demo", "record_candidates": False}, ctx
                )
            self.assertEqual(captured["db_path"], str(full_path))
            self.assertEqual(payload["strategy"], "demo")
        finally:
            full.close()
            hot.close()
            self.temp.cleanup()

    def test_execute_screen_hot_lag_falls_back_to_full(self) -> None:
        """热库落后于全量时回退全量库选股。"""
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        full_path = root / "market.db"
        hot_path = root / "market_hot.db"
        full = MarketStore(full_path)
        hot = MarketStore(hot_path)
        try:
            for code in ("000001", "600519"):
                _insert_instrument(full, code, f"票{code}")
                _insert_quote(full, "2026-07-30", code)
                _insert_quote(full, "2026-07-31", code)
            execute_hot_rebuild(
                {}, JobContext(market_db=full_path, market_hot_db=hot_path)
            )
            # 全量再补一日，但镜像被 stub 成空操作 → 热库落后
            for code in ("000001", "600519"):
                _insert_quote(full, "2026-08-03", code)

            captured: dict[str, object] = {}

            def fake_screen(store, _slug, **_kwargs):
                captured["db_path"] = str(store.db_path)
                return self._fake_screen_result("2026-08-03")

            ctx = JobContext(market_db=full_path, market_hot_db=hot_path)
            with (
                patch("src.market.apply_today_spot", lambda *_a, **_k: 0),
                patch("src.strategy.get", lambda _slug: SimpleNamespace(name="演示")),
                patch("src.strategy.screen", fake_screen),
                patch(
                    "src.market.mirror_recent_to_hot",
                    lambda *_a, **_k: {"mode": "incremental", "quotes": 0},
                ),
            ):
                payload = execute_screen(
                    {
                        "strategy": "demo",
                        "record_candidates": False,
                        "refresh_spot": False,
                    },
                    ctx,
                )
            self.assertEqual(captured["db_path"], str(full_path))
            self.assertEqual(payload["strategy"], "demo")
        finally:
            full.close()
            hot.close()
            self.temp.cleanup()

    def test_execute_screen_requires_full_history_skips_hot(self) -> None:
        """requires_full_history 策略跳过镜像，直接读全量库。"""
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        full_path = root / "market.db"
        hot_path = root / "market_hot.db"
        full = MarketStore(full_path)
        hot = MarketStore(hot_path)
        try:
            for code in ("000001", "600519"):
                _insert_instrument(full, code, f"票{code}")
                _insert_quote(full, "2026-07-30", code)
                _insert_quote(full, "2026-07-31", code)
            execute_hot_rebuild(
                {}, JobContext(market_db=full_path, market_hot_db=hot_path)
            )

            captured: dict[str, object] = {}
            mirror_calls: list[object] = []

            def fake_screen(store, _slug, **_kwargs):
                captured["db_path"] = str(store.db_path)
                return self._fake_screen_result()

            def fake_mirror(*_a, **_k):
                mirror_calls.append(1)
                return {"mode": "incremental"}

            ctx = JobContext(market_db=full_path, market_hot_db=hot_path)
            with (
                patch("src.market.apply_today_spot", lambda *_a, **_k: 0),
                patch(
                    "src.strategy.get",
                    lambda _slug: SimpleNamespace(
                        name="演示", requires_full_history=True
                    ),
                ),
                patch("src.strategy.screen", fake_screen),
                patch("src.market.mirror_recent_to_hot", side_effect=fake_mirror),
            ):
                payload = execute_screen(
                    {
                        "strategy": "demo",
                        "record_candidates": False,
                        "refresh_spot": False,
                    },
                    ctx,
                )
            self.assertEqual(captured["db_path"], str(full_path))
            self.assertEqual(mirror_calls, [])
            self.assertEqual(payload["strategy"], "demo")
        finally:
            full.close()
            hot.close()
            self.temp.cleanup()


class SyncHotMirrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.full_path = root / "market.db"
        self.hot_path = root / "market_hot.db"
        self.full = MarketStore(self.full_path)
        self.hot = MarketStore(self.hot_path)
        _insert_instrument(self.full, "000001", "平安银行")
        _insert_quote(self.full, "2026-07-30", "000001")
        _insert_quote(self.full, "2026-07-31", "000001")

    def tearDown(self) -> None:
        self.full.close()
        self.hot.close()
        self.temp.cleanup()

    def _report(self) -> SimpleNamespace:
        return SimpleNamespace(
            total=1,
            succeeded=1,
            skipped=0,
            failed=0,
            rows_written=2,
            failures=[],
            source_receipts=[],
            selected_sources={},
            unresolved_codes=[],
            elapsed_seconds=0.5,
        )

    def _patches(self) -> list:
        return [
            patch("src.market.sync_quotes", lambda *_a, **_k: self._report()),
            patch("src.market.apply_today_spot", lambda *_a, **_k: 1),
            patch("src.market.sync_instruments", lambda *_a, **_k: None),
            patch("src.market.refresh_adjust_factors", lambda *_a, **_k: 0),
            patch("src.market.backfill_missing_turnover", lambda *_a, **_k: {}),
        ]

    def test_execute_sync_mirrors_to_hot(self) -> None:
        ctx = JobContext(market_db=self.full_path, market_hot_db=self.hot_path)
        with ExitStack() as stack:
            for item in self._patches():
                stack.enter_context(item)
            payload = execute_sync({}, ctx)
        self.assertEqual(payload["mode"], "full")
        # 空热库首次镜像会升级为 rebuild；已灌满则 incremental。
        self.assertIn(payload["hot_mirror"]["mode"], {"rebuild", "incremental"})
        self.assertIn("quotes", payload["hot_mirror"])
        self.assertGreater(_quote_count(self.hot), 0)

    def test_hot_mirror_failure_does_not_fail_sync(self) -> None:
        ctx = JobContext(market_db=self.full_path, market_hot_db=self.hot_path)
        with ExitStack() as stack:
            for item in self._patches():
                stack.enter_context(item)
            stack.enter_context(
                patch(
                    "src.market.mirror_recent_to_hot",
                    side_effect=RuntimeError("hot db busy"),
                )
            )
            payload = execute_sync({}, ctx)
        self.assertEqual(payload["mode"], "full")
        self.assertEqual(payload["hot_mirror"]["error"], "hot db busy")
        # 热库镜像失败不影响同步结果字段
        self.assertEqual(payload["succeeded"], 1)


if __name__ == "__main__":
    unittest.main()