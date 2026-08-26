"""出口契约 + 录制夹具：对方改字段时先换夹具，再改 FieldSpec。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.market.domain.source_contract import (
    CAPITAL_FLOW_CONTRACT,
    DAILY_CONTRACT,
    INSTRUMENTS_BJ_CONTRACT,
    INSTRUMENTS_SH_CONTRACT,
    INSTRUMENTS_SZ_CONTRACT,
    LIVE_CONTRACT,
    MINUTE_CONTRACT,
    SPOT_CONTRACT,
)
from src.market.infrastructure.adapters.types import DAILY_REQUIRED_COLUMNS as TYPES_REQUIRED
from src.market.infrastructure.pipeline import NormalizeError, normalize

FIXTURES = Path(__file__).parent / "fixtures"


def _load(rel: str) -> pd.DataFrame:
    payload = json.loads((FIXTURES / rel).read_text(encoding="utf-8"))
    return pd.DataFrame(payload)


def test_daily_required_columns_match_contract() -> None:
    assert TYPES_REQUIRED == DAILY_CONTRACT.required_columns()


def test_eastmoney_daily_fixture_units() -> None:
    out = normalize(_load("eastmoney/hist_daily.json"), DAILY_CONTRACT, who="东财")
    assert list(out.columns)[:7] == list(DAILY_CONTRACT.required_columns())
    assert float(out["volume"].iloc[0]) == 100_000.0
    assert float(out["turnover"].iloc[0]) == pytest.approx(0.05)


def test_eastmoney_spot_fixture() -> None:
    out = normalize(_load("eastmoney/spot_batch.json"), SPOT_CONTRACT, who="东财")
    assert out["code"].iloc[0] == "600519"
    assert set(SPOT_CONTRACT.required_columns()).issubset(out.columns)
    # 东财现价「成交量」为手 → 股
    assert float(out["volume"].iloc[0]) == pytest.approx(1_234_500.0)


def test_eastmoney_minute_fixture() -> None:
    out = normalize(
        _load("eastmoney/minute_bars.json"),
        MINUTE_CONTRACT,
        who="东财分钟",
    )
    assert "datetime" in out.columns
    assert float(out["close"].iloc[0]) == pytest.approx(10.1)


def test_eastmoney_capital_flow_pct_chg_override() -> None:
    out = normalize(
        _load("eastmoney/capital_flow.json"),
        CAPITAL_FLOW_CONTRACT,
        who="东财资金流",
    )
    assert "pct_chg" in out.columns
    assert "pct" not in out.columns
    assert float(out["pct_chg"].iloc[0]) == pytest.approx(1.2)


def test_sina_daily_fixture_no_double_unit() -> None:
    out = normalize(_load("sina/hist_daily.json"), DAILY_CONTRACT, who="新浪")
    assert float(out["turnover"].iloc[0]) == pytest.approx(0.05)
    assert float(out["volume"].iloc[0]) == pytest.approx(100_000.0)
    assert "outstanding_share" in out.columns


def test_sina_spot_english_volume_not_scaled() -> None:
    out = normalize(_load("sina/spot_batch.json"), SPOT_CONTRACT, who="新浪")
    assert float(out["volume"].iloc[0]) == pytest.approx(1_234_500.0)


def test_tencent_daily_fixture() -> None:
    out = normalize(_load("tencent/hist_daily.json"), DAILY_CONTRACT, who="腾讯")
    assert set(DAILY_CONTRACT.required_columns()).issubset(out.columns)


def test_tencent_spot_english_volume_not_scaled() -> None:
    out = normalize(_load("tencent/spot_batch.json"), SPOT_CONTRACT, who="腾讯")
    assert float(out["volume"].iloc[0]) == pytest.approx(53100.0)


def test_baostock_turn_percent_to_ratio() -> None:
    out = normalize(_load("baostock/hist_daily.json"), DAILY_CONTRACT, who="证券宝")
    assert float(out["turnover"].iloc[0]) == pytest.approx(0.05)


def test_exchange_list_sh_fixture() -> None:
    out = normalize(
        _load("exchange_list/sh.json"),
        INSTRUMENTS_SH_CONTRACT,
        who="上交所",
    )
    assert out["code"].iloc[0] == "600519"
    assert out["name"].iloc[0] == "贵州茅台"


def test_exchange_list_sz_fixture() -> None:
    out = normalize(
        _load("exchange_list/sz.json"),
        INSTRUMENTS_SZ_CONTRACT,
        who="深交所",
    )
    assert out["code"].iloc[0] == "000001"
    assert out["board"].iloc[0] == "主板"
    assert out["industry"].iloc[0] == "J 金融业"


def test_exchange_list_bj_fixture() -> None:
    out = normalize(
        _load("exchange_list/bj.json"),
        INSTRUMENTS_BJ_CONTRACT,
        who="北交所",
    )
    assert out["code"].iloc[0] == "830799"


def test_normalize_rejects_empty_and_missing() -> None:
    with pytest.raises(NormalizeError, match="为空"):
        normalize(pd.DataFrame(), DAILY_CONTRACT, who="测", empty_label="测日线")
    with pytest.raises(NormalizeError, match="缺列"):
        normalize(pd.DataFrame({"date": ["2026-01-01"]}), DAILY_CONTRACT, who="测")


def test_keep_unmapped_retains_extra_columns() -> None:
    raw = pd.DataFrame(
        {
            "代码": ["600519"],
            "最新价": [10.0],
            "今开": [9.0],
            "最高": [11.0],
            "最低": [8.0],
            "成交量": [100.0],
            "成交额": [1e6],
            "extra_flag": ["keep-me"],
        }
    )
    out = normalize(raw, LIVE_CONTRACT, who="测")
    assert "extra_flag" in out.columns
    assert out["extra_flag"].iloc[0] == "keep-me"


def test_existing_target_column_is_not_overwritten() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-01-05"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "收盘": [99.0],
            "volume": [1000.0],
            "amount": [1e6],
        }
    )
    out = normalize(raw, DAILY_CONTRACT, who="测")
    assert float(out["close"].iloc[0]) == pytest.approx(10.5)


def test_existing_english_volume_wins_over_chinese_lots() -> None:
    """目标列已在时保留仓内口径，不把并列的中文「成交量」盖上去再 ×100。"""
    raw = pd.DataFrame(
        {
            "日期": ["2026-01-05"],
            "开盘": [1.0],
            "最高": [2.0],
            "最低": [0.5],
            "收盘": [1.5],
            "成交量": [10.0],
            "volume": [999.0],
            "成交额": [100.0],
        }
    )
    out = normalize(raw, DAILY_CONTRACT, who="测")
    assert float(out["volume"].iloc[0]) == pytest.approx(999.0)


def test_first_chinese_alias_wins_when_target_absent() -> None:
    raw = pd.DataFrame(
        {
            "代码": ["600519"],
            "今开": [1.0],
            "开盘": [9.0],
            "最高": [2.0],
            "最低": [0.5],
            "最新价": [1.5],
            "成交量": [10.0],
            "成交额": [100.0],
        }
    )
    out = normalize(raw, SPOT_CONTRACT, who="测")
    assert float(out["open"].iloc[0]) == pytest.approx(1.0)
