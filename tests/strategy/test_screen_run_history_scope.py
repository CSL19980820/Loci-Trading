"""历史选股的存储选择必须服从计算窗口，而非热库相对今天的健康状态。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from src.market import MarketStore
from src.strategy.application.screen_run import execute_screen_run, screen_run_snapshot
from tests.strategy.test_screen_run_hot import _fake_result, _seed


@pytest.mark.parametrize("start_index,end_index,missing_index,expected", [
    (5, 6, None, "full"),       # 整段历史已在热库之外。
    (20, 21, None, "full"),     # 目标日存在，但指标预热不够。
    (33, 34, None, "hot"),      # 最早一天的 21 根预热及整个区间均在热库。
    (33, 34, 34, "full"),       # 首日够用，区间内另一天缺失。
    (33, 34, 20, "full"),       # 首尾够长，中间缺一个预热交易日。
])
def test_storage_covers_entire_history_window(
    tmp_path: Path, start_index: int, end_index: int,
    missing_index: int | None, expected: str,
) -> None:
    days = pd.bdate_range("2024-01-01", periods=35).strftime("%Y-%m-%d").tolist()
    paths = {name: tmp_path / f"{name}.db" for name in ("full", "hot")}
    with MarketStore(paths["full"]) as full, MarketStore(paths["hot"]) as hot:
        _seed(full, ["000001"], days)
        _seed(hot, ["000001"], [day for i, day in enumerate(days) if i >= 12 and i != missing_index])
    selected: list[Path] = []

    def fake_screen(store: MarketStore, slug: str, **kwargs: object) -> SimpleNamespace:
        selected.append(store.db_path)
        assert kwargs.get("data_snapshot") is None
        return _fake_result(str(kwargs["trade_date"]), str(store.db_path))

    engine = SimpleNamespace(requires_full_history=False, min_bars=lambda: 1)
    with (
        patch("src.strategy.get", return_value=engine),
        patch("src.strategy.screen", side_effect=fake_screen),
        patch("src.market.mirror_recent_to_hot"),
        # 判据现在收口在 hot_fallback_reason 内部；patch 包根那个名字打不中它，
 # 用例会退化成「热库窗口偏浅恒回退」而不再检验预热日历。
        patch("src.market.infrastructure.store_hot.hot_unusable_reason", return_value=""),
    ):
        execute_screen_run(
            {"strategy": "demo", "start": days[start_index], "end": days[end_index],
             "record_candidates": False, "skip_health_check": True, "refresh_spot": False},
            market_factory=lambda: MarketStore(paths["full"]),
            palace_db=None, hot_db=str(paths["hot"]),
        )
    assert screen_run_snapshot()["status"] == "done"
    assert selected == [paths[expected]] * (end_index - start_index + 1)
