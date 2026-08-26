"""降级结构：熔断、门闩名额、失败文案与墙钟超时 —— 不打真网。

覆盖五处「一个源挂了别拖垮整轮 / 别看不懂为什么挂」的行为：
1. ``circuit`` 每源熔断（开路 / 半开 / 恢复）
2. ``fetch_daily_best`` 熔断后短路，且空表不算失败
3. 门闩按 lane 给在途名额：日 K 放小并发，其余 lane 仍单飞
4. 日 K 启用源全灭时回退已关闭源；全灭才把关掉的源写进错误
5. ``fetch_instruments_routed`` / ``speedtest_daily`` 的墙钟超时对
   「卡死不返回」的源真的有效（历史上被线程池 ``with`` 退出时的 join 吃掉）
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
import unittest
from unittest import mock

import pandas as pd

from src.market.infrastructure.adapters import circuit
from src.market.infrastructure.adapters.aux_router import fetch_instruments_routed
from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.registry import (
    enabled_adapter_ids,
    lane_disabled_provider_ids,
    reset_registry,
)
from src.market.infrastructure.adapters.router import (
    clear_sticky,
    fetch_daily_best,
    fetch_daily_routed,
    peek_sticky,
    speedtest_daily,
)
from src.market.infrastructure.adapters.router_live import (
    _try_claim_adapter,
    clear_adapter_gates,
    lane_concurrency,
)
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    LANE_HIST_DAILY,
    LANE_INSTRUMENTS,
    LANE_SPOT_BATCH,
)

LANE = LANE_HIST_DAILY


def _daily_frame(n: int = 2) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [f"2026-01-{i:02d}" for i in range(1, n + 1)],
            "open": [10.0] * n,
            "high": [11.0] * n,
            "low": [9.0] * n,
            "close": [10.5] * n,
            "volume": [1_000_000.0] * n,
            "amount": [10_500_000.0] * n,
        }
    )


class _Adapter(MarketAdapter):
    """可控行为的假源：正常 / 抛错 / 空表 / 睡死。"""

    def __init__(
        self,
        adapter_id: str,
        *,
        lanes: tuple[str, ...] = (LANE_HIST_DAILY,),
        fail: bool = False,
        empty: bool = False,
        sleep: float = 0.0,
        release: threading.Event | None = None,
    ) -> None:
        self.meta = AdapterMeta(id=adapter_id, label=adapter_id, lanes=lanes, description="fake")
        self.fail = fail
        self.empty = empty
        self.sleep = sleep
        # 测试结束时放行「睡死」线程，避免残留线程拖慢整个 pytest 进程退出。
        self.release = release
        self.daily_calls = 0
        self.instrument_calls = 0

    def _hang(self) -> None:
        if not self.sleep:
            return
        if self.release is not None:
            self.release.wait(self.sleep)
        else:
            time.sleep(self.sleep)

    def _payload(self) -> pd.DataFrame:
        self._hang()
        if self.fail:
            raise AdapterError(f"{self.meta.id} 故意失败")
        return pd.DataFrame() if self.empty else _daily_frame()

    def fetch_daily(self, code: str, *, instrument_type: str = "STOCK") -> pd.DataFrame:
        self.daily_calls += 1
        return self._payload()

    def fetch_instruments(self) -> pd.DataFrame:
        self.instrument_calls += 1
        self._hang()
        if self.fail:
            raise AdapterError(f"{self.meta.id} 故意失败")
        return pd.DataFrame() if self.empty else pd.DataFrame([{"code": "600519"}])


class CircuitTests(unittest.TestCase):
    """熔断器自身的状态机，用注入时钟保证确定性。"""

    def tearDown(self) -> None:
        circuit.reset()

    def test_opens_only_after_the_threshold(self) -> None:
        for _ in range(circuit.FAILURE_THRESHOLD - 1):
            circuit.record_failure(LANE, "src", now=100.0)
        self.assertTrue(circuit.acquire(LANE, "src", now=100.0))
        circuit.record_failure(LANE, "src", now=100.0)
        self.assertFalse(circuit.acquire(LANE, "src", now=100.0))

    def test_success_resets_the_streak(self) -> None:
        for _ in range(circuit.FAILURE_THRESHOLD - 1):
            circuit.record_failure(LANE, "src", now=100.0)
        circuit.record_success(LANE, "src")
        for _ in range(circuit.FAILURE_THRESHOLD - 1):
            circuit.record_failure(LANE, "src", now=100.0)
        self.assertTrue(circuit.acquire(LANE, "src", now=100.0))

    def test_half_open_lets_exactly_one_probe_through(self) -> None:
        for _ in range(circuit.FAILURE_THRESHOLD):
            circuit.record_failure(LANE, "src", now=100.0)
        due = 100.0 + circuit.COOLDOWN_SEC
        self.assertFalse(circuit.acquire(LANE, "src", now=due - 1.0))
        self.assertTrue(circuit.acquire(LANE, "src", now=due))
        # 探针在途期间不能再放第二个请求进去
        self.assertFalse(circuit.acquire(LANE, "src", now=due + 1.0))
        circuit.record_success(LANE, "src")
        self.assertTrue(circuit.acquire(LANE, "src", now=due + 2.0))

    def test_cooldown_remaining_is_zero_when_closed(self) -> None:
        self.assertEqual(circuit.cooldown_remaining(LANE, "src", now=1.0), 0.0)
        for _ in range(circuit.FAILURE_THRESHOLD):
            circuit.record_failure(LANE, "src", now=100.0)
        self.assertGreater(circuit.cooldown_remaining(LANE, "src", now=100.0), 0.0)

    def test_lanes_do_not_share_state(self) -> None:
        for _ in range(circuit.FAILURE_THRESHOLD):
            circuit.record_failure(LANE, "src", now=100.0)
        self.assertTrue(circuit.acquire("minute_bars", "src", now=100.0))


class DailyCircuitWiringTests(unittest.TestCase):
    """``fetch_daily_best`` 与熔断器的接线。"""

    def setUp(self) -> None:
        circuit.reset()

    def tearDown(self) -> None:
        circuit.reset()
        reset_registry()

    def test_dead_source_is_skipped_once_the_breaker_opens(self) -> None:
        dead = _Adapter("dead_src", fail=True)
        alive = _Adapter("alive_src")
        reset_registry([dead, alive])

        for _ in range(circuit.FAILURE_THRESHOLD):
            frame, winner = fetch_daily_best("600519", max_workers=2)
            self.assertEqual(winner, "alive_src")
            self.assertEqual(len(frame), 2)
        self.assertEqual(dead.daily_calls, circuit.FAILURE_THRESHOLD)

        receipt: list[dict] = []
        fetch_daily_best("600519", max_workers=2, receipt=receipt)
        self.assertEqual(dead.daily_calls, circuit.FAILURE_THRESHOLD)  # 不再打
        skipped = [r for r in receipt if r.get("source_id") == "dead_src"]
        self.assertTrue(skipped and "熔断" in str(skipped[0].get("error")))

    def test_empty_result_never_trips_the_breaker(self) -> None:
        """源答了但没这只票 ≠ 源挂了；否则几只退市票就能打下线一个健康源。"""
        thin = _Adapter("thin_src", empty=True)
        alive = _Adapter("alive_src")
        reset_registry([thin, alive])

        rounds = circuit.FAILURE_THRESHOLD + 2
        for _ in range(rounds):
            fetch_daily_best("600519", max_workers=2)
        self.assertEqual(thin.daily_calls, rounds)

    def test_all_sources_open_fails_fast_with_a_readable_reason(self) -> None:
        dead = _Adapter("dead_only", fail=True)
        reset_registry([dead])
        for _ in range(circuit.FAILURE_THRESHOLD):
            with self.assertRaises(AdapterError):
                fetch_daily_best("600519")
        with self.assertRaises(AdapterError) as ctx:
            fetch_daily_best("600519")
        self.assertIn("熔断", str(ctx.exception))
        self.assertEqual(dead.daily_calls, circuit.FAILURE_THRESHOLD)


class SwitchedOffProviderMessageTests(unittest.TestCase):
    """关掉的源不进日常合并；启用源全灭时才作最后回退。"""

    def setUp(self) -> None:
        circuit.reset()

    def tearDown(self) -> None:
        circuit.reset()
        clear_sticky()
        reset_registry()

    def test_daily_falls_back_to_switched_off_provider(self) -> None:
        survivor = _Adapter("survivor", fail=True)
        parked = _Adapter("parked")
        reset_registry([survivor, parked])
        config = {"lane_providers": {"parked": {"lanes": {LANE_HIST_DAILY: False}}}}
        receipt: list[dict] = []
        with mock.patch("src.shared.paths.load_config", return_value=config):
            self.assertEqual(lane_disabled_provider_ids(LANE_HIST_DAILY), ["parked"])
            self.assertEqual(enabled_adapter_ids(LANE_HIST_DAILY), ["survivor"])
            frame, winner = fetch_daily_routed("600519", receipt=receipt)
        self.assertEqual(winner, "parked")
        self.assertEqual(len(frame), 2)
        self.assertEqual(parked.daily_calls, 1)
        self.assertTrue(any(item.get("state") == "emergency" for item in receipt))
        # 回退命中不钉粘性，腾讯恢复后下一票仍走启用源。
        self.assertIsNone(peek_sticky(LANE_HIST_DAILY))

    def test_daily_failure_names_providers_when_last_resort_also_fails(self) -> None:
        survivor = _Adapter("survivor", fail=True)
        parked = _Adapter("parked", fail=True)
        reset_registry([survivor, parked])
        config = {"lane_providers": {"parked": {"lanes": {LANE_HIST_DAILY: False}}}}
        with mock.patch("src.shared.paths.load_config", return_value=config):
            with self.assertRaises(AdapterError) as ctx:
                fetch_daily_routed("600519")
        message = str(ctx.exception)
        self.assertEqual(parked.daily_calls, 1)
        self.assertIn("parked", message)
        self.assertIn("只剩 1 个启用源", message)
        self.assertIn("最后回退仍失败", message)

    def test_manual_lock_without_fallback_does_not_touch_parked(self) -> None:
        survivor = _Adapter("survivor", fail=True)
        parked = _Adapter("parked")
        reset_registry([survivor, parked])
        config = {
            "lane_providers": {"parked": {"lanes": {LANE_HIST_DAILY: False}}},
            "lane_routes": {
                LANE_HIST_DAILY: {
                    "mode": "manual",
                    "provider_id": "survivor",
                    "fallback": False,
                }
            },
        }
        with mock.patch("src.shared.paths.load_config", return_value=config):
            with self.assertRaises(AdapterError) as ctx:
                fetch_daily_routed("600519")
        self.assertEqual(parked.daily_calls, 0)
        self.assertIn("未开失败回退", str(ctx.exception))

    def test_daily_failure_stays_plain_when_every_provider_is_enabled(self) -> None:
        reset_registry([_Adapter("a", fail=True), _Adapter("b", fail=True)])
        with mock.patch("src.shared.paths.load_config", return_value={}):
            with self.assertRaises(AdapterError) as ctx:
                fetch_daily_routed("600519")
        # 没人被关掉时别挂个「已关闭」的尾巴去误导排查
        self.assertNotIn("已在运维", str(ctx.exception))


class _ConcurrencyProbe(MarketAdapter):
    """记录同一时刻在途请求数的假源。"""

    def __init__(self, adapter_id: str, *, hold: float) -> None:
        self.meta = AdapterMeta(
            id=adapter_id, label=adapter_id, lanes=(LANE_HIST_DAILY,), description="fake"
        )
        self.hold = hold
        self.max_in_flight = 0
        self._in_flight = 0
        self._lock = threading.Lock()

    def fetch_daily(self, code: str, *, instrument_type: str = "STOCK") -> pd.DataFrame:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            time.sleep(self.hold)
            return _daily_frame()
        finally:
            with self._lock:
                self._in_flight -= 1


class AdapterGateTests(unittest.TestCase):
    """门闩名额：日 K 放小并发，其余 lane 保持单飞。"""

    def tearDown(self) -> None:
        clear_adapter_gates()
        reset_registry()

    def test_hist_daily_grants_several_in_flight_slots_per_source(self) -> None:
        limit = lane_concurrency(LANE_HIST_DAILY)
        self.assertGreater(limit, 1, "日 K 单飞会把全市场同步串成一条连接")
        claims = [_try_claim_adapter(LANE_HIST_DAILY, "src") for _ in range(limit)]
        self.assertNotIn(None, claims)
        # 名额用尽仍要挡住下一条：放开并发不等于取消限流
        self.assertIsNone(_try_claim_adapter(LANE_HIST_DAILY, "src"))
        for claim in claims:
            assert claim is not None
            claim.release()
        self.assertIsNotNone(_try_claim_adapter(LANE_HIST_DAILY, "src"))

    def test_other_lanes_stay_single_flight(self) -> None:
        first = _try_claim_adapter(LANE_SPOT_BATCH, "src")
        self.assertIsNotNone(first)
        self.assertIsNone(_try_claim_adapter(LANE_SPOT_BATCH, "src"))

    def test_one_source_serves_several_codes_at_once(self) -> None:
        probe = _ConcurrencyProbe("probe_src", hold=0.15)
        reset_registry([probe])
        codes = ["600519", "000001", "600036"]
        with ThreadPoolExecutor(max_workers=len(codes)) as pool:
            winners = list(pool.map(lambda code: fetch_daily_best(code)[1], codes))
        self.assertEqual(winners, ["probe_src"] * len(codes))
        self.assertGreater(probe.max_in_flight, 1, "同一来源的不同代码仍被串成一条")


class WallClockTimeoutTests(unittest.TestCase):
    """卡死的源不能吃掉超时。睡死线程无法取消，故只断言「调用方按时脱身」。

    挂死时长（20s）远大于超时（1s）：若线程池退出时又 join 回去，耗时会直接
    穿过 3s 的上界，测试红。
    """

    def setUp(self) -> None:
        self.release = threading.Event()

    def tearDown(self) -> None:
        self.release.set()
        reset_registry()

    def test_instruments_moves_on_when_a_source_hangs(self) -> None:
        hanging = _Adapter(
            "hang_list", lanes=(LANE_INSTRUMENTS,), sleep=20.0, release=self.release
        )
        quick = _Adapter("quick_list", lanes=(LANE_INSTRUMENTS,))
        reset_registry([hanging, quick])

        started = time.perf_counter()
        frame, aid = fetch_instruments_routed(timeout_sec=1.0)
        elapsed = time.perf_counter() - started

        self.assertEqual(aid, "quick_list")
        self.assertEqual(len(frame), 1)
        self.assertLess(elapsed, 3.0, "超时后仍在等挂死的源")

    def test_speedtest_reports_a_hanging_source_instead_of_blocking(self) -> None:
        hanging = _Adapter("hang_speed", sleep=20.0, release=self.release)
        quick = _Adapter("quick_speed")
        reset_registry([hanging, quick])

        started = time.perf_counter()
        results = speedtest_daily("600519", max_workers=2, timeout_sec=1.0)
        elapsed = time.perf_counter() - started

        by_id = {item.adapter_id: item for item in results}
        self.assertTrue(by_id["quick_speed"].ok)
        self.assertFalse(by_id["hang_speed"].ok)
        self.assertIn("超时", by_id["hang_speed"].error or "")
        self.assertLess(elapsed, 3.0, "测速被挂死的源拖住")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
