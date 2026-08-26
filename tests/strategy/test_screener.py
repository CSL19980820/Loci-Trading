from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from src.market.domain.universe import ResolvedUniverse
from src.strategy.application.screener import screen
from src.strategy.domain.base import SignalResult


class _PanelStore:
    def __init__(self, days: list[str]) -> None:
        self.days = days
        self.volume = pd.DataFrame({"600001": [1.0] * len(days)}, index=days)
        self.load_args: dict[str, object] = {}
        self.snapshot_args: dict[str, object] = {}

    def trading_days(self, *, end: str | None = None) -> list[str]:
        return [day for day in self.days if end is None or day <= end]

    def data_snapshot(self, **kwargs: object) -> dict[str, object]:
        self.snapshot_args = dict(kwargs)
        return {"revision": "test"}

    def load_panel(self, **kwargs: object) -> dict[str, pd.DataFrame]:
        self.load_args = kwargs
        start = str(kwargs["start"])
        end = str(kwargs["end"])
        return {"volume": self.volume.loc[start:end]}


class _VolumeOnlyEngine:
    slug = "volume-only"
    name = "成交量测试"
    description = "只依赖成交量"
    entry_timing = "next_open"
    strategy_revision = "test"

    def __init__(
        self,
        *,
        requires_full_history: bool = False,
        warmup_bars: int | None = None,
        watch_only: bool = False,
    ) -> None:
        self.requires_full_history = requires_full_history
        self.watch_only = watch_only
        if warmup_bars is not None:
            self.warmup_bars = warmup_bars

    def default_params(self) -> dict[str, object]:
        return {}

    def required_fields(self) -> tuple[str, ...]:
        return ("volume",)

    def min_bars(self) -> int:
        return 2

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, object] | None = None
    ) -> SignalResult:
        volume = panels["volume"]
        return SignalResult(
            signals=volume.gt(1) if self.watch_only else volume.gt(0),
            watch_signals=volume.gt(0) if self.watch_only else None,
            factors={"成交量": volume},
        )


class ScreenerPanelSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.days = [f"2026-01-{day:02d}" for day in range(2, 22)]
        self.resolved = ResolvedUniverse(
            codes=["600001"],
            meta={"600001": {"name": "示例"}},
            spec={"preset": "test"},
        )

    def _screen(self, store: _PanelStore, engine: _VolumeOnlyEngine):
        with patch(
            "src.strategy.application.screener.resolve_universe", return_value=self.resolved
        ):
            return screen(store, engine, codes=["600001"], extra_bars=0)

    def test_volume_only_strategy_runs_without_a_close_panel(self) -> None:
        result = self._screen(_PanelStore(self.days), _VolumeOnlyEngine())

        self.assertEqual([pick["code"] for pick in result.picks], ["600001"])
        self.assertIsNone(result.picks[0]["close"])
        self.assertEqual(result.universe_size, 1)

    def test_watch_signals_are_enriched_without_becoming_formal_picks(self) -> None:
        result = self._screen(
            _PanelStore(self.days), _VolumeOnlyEngine(watch_only=True)
        )

        self.assertEqual(result.picks, [])
        self.assertEqual([pick["code"] for pick in result.watch_picks], ["600001"])
        self.assertEqual(result.watch_picks[0]["intent"], "observe")

    def test_data_snapshot_receives_universe_and_window(self) -> None:
        store = _PanelStore(self.days)
        result = self._screen(store, _VolumeOnlyEngine())

        # 选股必须在解析宇宙后带 codes+窗口取证，禁止无范围全库扫证据
        self.assertEqual(store.snapshot_args["codes"], ["600001"])
        self.assertEqual(store.snapshot_args["end"], self.days[-1])
        self.assertIn("start", store.snapshot_args)
        self.assertEqual(result.data_snapshot["start"], store.snapshot_args["start"])
        self.assertEqual(result.data_snapshot["end"], store.snapshot_args["end"])

    def test_stateful_strategy_loads_full_available_history(self) -> None:
        store = _PanelStore(self.days)
        result = self._screen(store, _VolumeOnlyEngine(requires_full_history=True))

        self.assertEqual(store.load_args["start"], self.days[0])
        self.assertEqual(result.data_snapshot["history_mode"], "full")

    def test_strategy_warmup_bars_are_used_by_the_screener(self) -> None:
        store = _PanelStore(self.days)
        self._screen(store, _VolumeOnlyEngine(warmup_bars=10))

        self.assertEqual(store.load_args["start"], self.days[-10])
        self.assertEqual(store.load_args["end"], self.days[-1])


if __name__ == "__main__":
    unittest.main()
