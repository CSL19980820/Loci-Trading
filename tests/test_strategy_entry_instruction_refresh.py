"""默认说明升级只命中已知原文，不覆盖人工档案或同名自定义战法。"""
from __future__ import annotations

import pytest

from src.ops import OpsStore


SLUG = "yangshi-tail-v1"
LEGACY_INSTRUCTIONS = (
    "T 日收盘后 15:30 执行（素材原文是尾盘选股：用已定型的收盘价选股，不在尾盘买入）。"
    "闸门：流通股本 < 2 亿股、未复权收盘价 < 12 元且 ≥ 3 元、"
    "当日涨幅 1% < pct < 5%、换手率 > 2%、成交额 ≥ 3000 万、"
    "当日未封涨停且非一字。原文第 6 条「净资产收益率 > 0.001%」因本仓无财务数据未实现。"
    "若当日市场上涨家数占比 < 40%，整日空仓；闸门前合格的 Top1 进入 watch_signals 观察，"
    "观察不进入回测也不生成次日预案。否则按当日涨幅降序取第一只。"
    "T+1 按开盘价买入（一字涨停买不进则跳过），持有 2 个交易日后于 T+3 收盘卖出；"
    "不设止损、不追高、不补仓，信号日收盘前不得使用次日数据。"
)
CURRENT_INSTRUCTIONS = "股票范围按统一配置；量价条件符合后评分，不另设绝对股价或股本门槛。"


def _strategy(**overrides):
    return {
        "slug": SLUG,
        "name": "杨氏尾盘选股",
        "source_kind": "builtin",
        "entry_timing": "next_open",
        "version": "v1.1",
        "entry_instructions": CURRENT_INSTRUCTIONS,
        **overrides,
    }


def test_known_default_refreshes_for_catalog_without_changing_other_doc_fields(tmp_path):
    with OpsStore(tmp_path / "ops.db") as store:
        store.upsert_strategy_doc(
            SLUG, name="保留我的档案名", source_text="保留原始资料", version="manual",
            entry_instructions=LEGACY_INSTRUCTIONS,
        )
        before = store.get_strategy_doc(SLUG)
        store.ensure_strategy_entry_instructions([_strategy()])
        after = store.get_strategy_doc(SLUG)
        assert after["entry_instructions"] == CURRENT_INSTRUCTIONS
        for key in ("name", "source_text", "version", "created_at"):
            assert after[key] == before[key]
        assert store.strategy_catalog_metadata([_strategy()])[SLUG]["entry_instructions"] == CURRENT_INSTRUCTIONS
        store.ensure_strategy_entry_instructions([_strategy()])
        assert store.get_strategy_doc(SLUG) == after


@pytest.mark.parametrize("instructions", [LEGACY_INSTRUCTIONS + "我只观察。", "只关注主板 ST 的人工预案"])
def test_user_edited_instructions_remain_unchanged(tmp_path, instructions):
    with OpsStore(tmp_path / "ops.db") as store:
        store.upsert_strategy_doc(SLUG, entry_instructions=instructions)
        before = store.get_strategy_doc(SLUG)
        store.ensure_strategy_entry_instructions([_strategy()])
        assert store.get_strategy_doc(SLUG) == before


@pytest.mark.parametrize("source_kind,slug", [("python", SLUG), ("builtin", "unrelated-strategy")])
def test_custom_or_unrelated_strategy_cannot_receive_builtin_default_upgrade(tmp_path, source_kind, slug):
    with OpsStore(tmp_path / "ops.db") as store:
        store.upsert_strategy_doc(slug, entry_instructions=LEGACY_INSTRUCTIONS)
        before = store.get_strategy_doc(slug)
        store.ensure_strategy_entry_instructions([_strategy(source_kind=source_kind, slug=slug)])
        assert store.get_strategy_doc(slug) == before


def test_missing_default_still_populates_doc(tmp_path):
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_strategy_entry_instructions([_strategy()])
        assert store.get_strategy_doc(SLUG)["entry_instructions"] == CURRENT_INSTRUCTIONS
