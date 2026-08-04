from __future__ import annotations

from pathlib import Path

import pytest

from src.ops import OpsError, OpsStore


def test_strategy_versions_are_deduplicated_and_keep_one_active(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        first = store.save_strategy_version("custom-demo", "code = 1")
        second = store.save_strategy_version("custom-demo", "code = 2")
        assert (first, second) == (1, 2)

        # 重复内容复用原版本，同时将它切回 active，不制造第三条历史。
        assert store.save_strategy_version("custom-demo", "code = 1") == first
        versions = store.list_strategy_versions("custom-demo")
        assert len(versions) == 2
        assert next(item for item in versions if item["version"] == first)["is_active"] is True

        restored = store.rollback_strategy_version("custom-demo", second)
        assert restored["is_active"] is True
        assert store.get_strategy_version("custom-demo")["version"] == second
        with pytest.raises(OpsError, match="不能删除当前 active"):
            store.delete_strategy_version("custom-demo", second)
        assert store.delete_strategy_version("custom-demo", first) is True


def test_backtest_metadata_is_idempotent_per_slug_and_version(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        saved = store.upsert_strategy_backtest(
            "screen-demo",
            "revision-a",
            metrics={
                "trades": 12,
                "win_rate": 58.33,
                "avg_net_return": 1.2,
                "profit_factor": 1.5,
            },
            config={"mode": "trade", "hold_days": 3},
        )
        updated = store.upsert_strategy_backtest(
            "screen-demo",
            "revision-a",
            metrics={
                "trades": 13,
                "win_rate": 60.0,
                "avg_net_return": 1.4,
                "profit_factor": 1.7,
            },
            config={"mode": "trade", "hold_days": 5},
        )
        assert saved["version"] == updated["version"] == "revision-a"
        loaded = store.get_strategy_backtest("screen-demo", "revision-a")
        assert loaded is not None
        assert loaded["metrics"]["trades"] == 13
        assert loaded["config"]["hold_days"] == 5


def test_strategy_entry_instructions_are_persisted_without_overwriting_manual_text(
    tmp_path: Path,
) -> None:
    strategies = [
        {
            "slug": "rsi30-dip",
            "name": "RSI22 次日低吸",
            "source_kind": "builtin",
            "entry_timing": "next_dip",
            "entry_instructions": "默认买入说明",
            "version": "v2",
        }
    ]
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_strategy_entry_instructions(strategies)
        assert store.get_strategy_doc("rsi30-dip")["entry_instructions"] == "默认买入说明"

        store.upsert_strategy_doc("rsi30-dip", entry_instructions="人工修改后的买入说明")
        store.ensure_strategy_entry_instructions(strategies)
        assert store.get_strategy_doc("rsi30-dip")["entry_instructions"] == "人工修改后的买入说明"
