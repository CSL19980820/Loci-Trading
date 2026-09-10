"""行情同步侧：设置存储、当日刷新与进度上报。

从 `test_notify_and_sync.py` 拆出（原 613 行，通知与同步两条线混在一起）。
通知用例见 `test_notify_and_sync.py`。
"""
from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pytest

from src.ops.application.jobs import JobContext, execute_sync
from src.ops.infrastructure.store import MANAGED_SYNC_INTRADAY, OpsStore


class _FakeSyncReport:
    """``sync_quotes`` 的最小替身返回值：execute_sync 只读这几个字段。"""

    succeeded = 0
    skipped = 0
    failed = 0
    rows_written = 0
    elapsed_seconds = 0.0


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch):
    """任何真实连接都让用例失败。

    **记账 + teardown 断言，不是当场抛**：行情适配器的契约就是「吞掉一切网络
    异常、回退下一个源」，在 connect 里抛错会被它自己接住翻译成一次「这个源
    不通」，用例照样绿。只抛不记的守卫对真实泄漏毫无反应。

    不是洁癖：本文件两条失败报告用例原先漏了 patch ``sync_quotes``，
    ``_finalize_today_with_authoritative`` 于是真去连通达信——实测 117 次真实
    connect（端口 7709 与 443），两条合计 40 秒，占全套 450 秒的 9%。

    守 ``socket.socket.connect`` 而不是 ``urlopen``：通达信走裸 socket，
    urlopen 拦不到它。
    """
    import socket

    leaked: list[str] = []

    def _spy(self, address):
        leaked.append(str(address))
        raise OSError("用例试图真的出网：行情源必须 mock")

    monkeypatch.setattr(socket.socket, "connect", _spy)
    yield
    assert not leaked, f"用例试图真的出网（行情源必须 mock）：{leaked[:5]}"


class MarketSyncSettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = OpsStore(Path(self.temp.name) / "ops.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_settings_kv_and_ensure_job(self) -> None:
        self.store.set_setting("wecom_webhook", {"url": "x"})
        self.assertEqual(self.store.get_setting("wecom_webhook")["url"], "x")
        job_id = self.store.ensure_job(
            name=MANAGED_SYNC_INTRADAY,
            kind="sync",
            cron="*/5 9-14 * * 1-5",
            config={"mode": "full"},
            enabled=True,
        )
        again = self.store.ensure_job(
            name=MANAGED_SYNC_INTRADAY,
            kind="sync",
            cron="*/15 9-14 * * 1-5",
            config={"mode": "full", "workers": 6},
            enabled=False,
        )
        self.assertEqual(job_id, again)
        job = self.store.get_job(job_id)
        self.assertEqual(job["cron"], "*/15 9-14 * * 1-5")
        self.assertFalse(job["enabled"])
        self.assertEqual(job["config"]["workers"], 6)


class TodayRefreshSyncTests(unittest.TestCase):
    def test_today_refresh_finalizes_with_authoritative_after_spot(self) -> None:
        """日终必须在 spot 之后再用权威源把当日重写成正式日 K。

        这里原先断言的是「today_refresh 不调 sync_quotes」——那条断言把 bug 本身锁成了
        契约。``quotes_daily`` 的 upsert 是后写覆盖先写，而 ``apply_today_spot`` 写进去
        的 source 恒带 ``_spot``：少了收尾这一趟，当日行在日终跑完之后仍然是临时行，
        正式日 K 要等第二天早上增量近窗回头重写才落。当天的 15:30 选股、当日回测与
        复盘读到的就是没有 source receipt、``amount`` 还可能是 ``close×volume`` 合成
        假值的行。

        **顺序也是断言的一部分**：反过来跑，spot 会把刚写好的正式日 K 重新盖成临时行，
        等于没修。
        """
        called = {"sync_quotes": 0, "spot": 0}
        order: list[str] = []

        class FakeStore:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def close(self) -> None:
                return None

            @property
            def conn(self):
                return None

            def list_instruments(self):
                return [{"code": "300358", "instrument_type": "STOCK"}]

            def trading_days(self, *_args, **_kwargs):
                return []

        def fake_sync_quotes(*_args, **_kwargs):
            called["sync_quotes"] += 1
            order.append("sync_quotes")
            return SimpleNamespace(
                total=1,
                succeeded=1,
                skipped=0,
                failed=0,
                rows_written=7,
                elapsed_seconds=1.5,
            )

        def fake_spot(_store, _codes, **_kwargs):
            called["spot"] += 1
            order.append("spot")
            return 3

        ctx = JobContext(market_db=":memory:")
        with (
            patch("src.market.MarketStore", FakeStore),
            patch("src.market.sync_instruments", lambda *_a, **_k: None),
            patch("src.market.sync_quotes", fake_sync_quotes),
            patch("src.market.apply_today_spot", fake_spot),
            patch(
                "src.market.infrastructure.sync.refresh_adjust_factors",
                lambda *_a, **_k: 0,
            ),
            patch("src.market.backfill_missing_turnover", lambda *_a, **_k: {}),
            patch(
                "src.market.mirror_recent_to_hot",
                lambda *_a, **_k: {"mode": "skip", "quotes": 0, "end": ""},
            ),
        ):
            result = execute_sync({"mode": "today_refresh"}, ctx)

        self.assertEqual(result["mode"], "today_refresh")
        self.assertEqual(result["spot_rows"], 3)
        self.assertEqual(called["spot"], 1)
        self.assertEqual(called["sync_quotes"], 1)
        self.assertEqual(order, ["spot", "sync_quotes"])
        self.assertEqual(result["finalize"]["status"], "ok")
        self.assertEqual(result["finalize"]["rows_written"], 7)
        # spot 3 行 + 定稿 7 行都要计进任务总写入，否则运维页少报一半
        self.assertEqual(result["rows_written"], 10)
        self.assertEqual(result["factors_error"], "")

    def test_factor_refresh_failure_is_reported_in_result(self) -> None:
        """复权因子刷不动只写日志＝静默失败：除权后 qfq 会长期失真。"""

        class FakeStore:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def close(self) -> None:
                return None

            def list_instruments(self):
                return [{"code": "300358", "instrument_type": "STOCK"}]

        def boom(*_args, **_kwargs):
            raise RuntimeError("复权源 SSL EOF")

        ctx = JobContext(market_db=":memory:")
        with (
            patch("src.market.MarketStore", FakeStore),
            patch("src.market.sync_instruments", lambda *_a, **_k: None),
            # 必须 patch：today_refresh 的 _finalize_today_with_authoritative 会调它，
            # 漏了就真去连通达信（实测 117 次真实 connect，两条用例合计 40 秒）。
            patch("src.market.sync_quotes", lambda *_a, **_k: _FakeSyncReport()),
            patch("src.market.apply_today_spot", lambda *_a, **_k: 1),
            patch("src.market.refresh_adjust_factors", boom),
            patch("src.market.backfill_missing_turnover", lambda *_a, **_k: {}),
            patch(
                "src.market.mirror_recent_to_hot",
                lambda *_a, **_k: {"mode": "skip", "quotes": 0, "end": ""},
            ),
        ):
            result = execute_sync(
                {"mode": "today_refresh", "with_factors": True}, ctx
            )

        self.assertEqual(result["factors_refreshed"], 0)
        self.assertIn("复权源 SSL EOF", result["factors_error"])
        # 现价照常补，任务本身不因尽力而为的因子刷新变红
        self.assertEqual(result["spot_rows"], 1)
        self.assertEqual(result["failed"], 0)

    def test_turnover_backfill_failure_is_reported_in_result(self) -> None:
        class FakeStore:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def close(self) -> None:
                return None

            def list_instruments(self):
                return [{"code": "300358", "instrument_type": "STOCK"}]

        def boom(*_args, **_kwargs):
            raise RuntimeError("换手率回填炸了")

        ctx = JobContext(market_db=":memory:")
        with (
            patch("src.market.MarketStore", FakeStore),
            patch("src.market.sync_instruments", lambda *_a, **_k: None),
            # 必须 patch：today_refresh 的 _finalize_today_with_authoritative 会调它，
            # 漏了就真去连通达信（实测 117 次真实 connect，两条用例合计 40 秒）。
            patch("src.market.sync_quotes", lambda *_a, **_k: _FakeSyncReport()),
            patch("src.market.apply_today_spot", lambda *_a, **_k: 1),
            patch("src.market.refresh_adjust_factors", lambda *_a, **_k: 0),
            patch("src.market.backfill_missing_turnover", boom),
            patch(
                "src.market.mirror_recent_to_hot",
                lambda *_a, **_k: {"mode": "skip", "quotes": 0, "end": ""},
            ),
        ):
            result = execute_sync({"mode": "today_refresh"}, ctx)

        self.assertIn("换手率回填炸了", result["turnover_repair"]["error"])


class SyncProgressTests(unittest.TestCase):
    def test_reports_total_before_first_quote_finishes(self) -> None:
        events: list[tuple[int, int, str]] = []

        def callback(done: int, total: int, code: str) -> None:
            events.append((done, total, code))

        class FakeStore:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def close(self) -> None:
                return None

            @property
            def conn(self):
                return None

            def list_instruments(self):
                return [
                    {"code": "600519", "instrument_type": "STOCK"},
                    {"code": "000001", "instrument_type": "STOCK"},
                ]

            def trading_days(self, *_args, **_kwargs):
                return []

        report = SimpleNamespace(
            total=2,
            succeeded=0,
            skipped=0,
            failed=0,
            rows_written=0,
            failures=[],
            elapsed_seconds=0.0,
            source_receipts=[],
            selected_sources={},
            unresolved_codes=[],
        )

        def fake_sync_quotes(*_args, **kwargs):
            self.assertEqual(events, [(0, 2, "")])
            self.assertIs(kwargs["progress"], callback)
            return report

        ctx = JobContext(market_db=":memory:")
        with (
            patch("src.market.MarketStore", FakeStore),
            patch("src.market.sync_instruments", lambda *_a, **_k: None),
            patch("src.market.sync_quotes", fake_sync_quotes),
            patch("src.market.apply_today_spot", lambda *_a, **_k: 0),
            patch("src.market.backfill_missing_turnover", lambda *_a, **_k: {}),
            patch(
                "src.market.mirror_recent_to_hot",
                lambda *_a, **_k: {"mode": "skip", "quotes": 0, "end": ""},
            ),
        ):
            execute_sync({}, ctx, progress=callback)
