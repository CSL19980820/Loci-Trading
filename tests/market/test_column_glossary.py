"""列名中英对照表：往返一致，且东财对照表在契约化后逐字不变。"""
from __future__ import annotations

from src.market.domain.column_glossary import CN_TO_EN, EN_TO_CN, gloss_column
from src.market.domain.source_contract import (
    EASTMONEY_CAPITAL_FLOW_RENAME,
    EASTMONEY_DAILY_RENAME,
    EASTMONEY_MINUTE_RENAME,
    EASTMONEY_SPOT_RENAME,
)
from src.market.infrastructure.adapters.types import (
    DAILY_OPTIONAL_COLUMNS,
    DAILY_REQUIRED_COLUMNS,
)


def test_gloss_column_round_trips_known_chinese_and_english_names() -> None:
    assert gloss_column("成交额") == {"raw": "成交额", "cn": "成交额", "en": "amount"}
    assert gloss_column("amount") == {"raw": "amount", "cn": "成交额", "en": "amount"}
    for chinese, english in CN_TO_EN.items():
        glossed = gloss_column(chinese)
        assert glossed["cn"] == chinese
        assert glossed["en"] == english
        assert gloss_column(english)["en"] == english


def test_gloss_column_never_guesses_a_translation() -> None:
    assert gloss_column("融资余额") == {"raw": "融资余额", "cn": "融资余额", "en": ""}
    assert gloss_column("margin_balance") == {
        "raw": "margin_balance",
        "cn": "",
        "en": "margin_balance",
    }
    assert gloss_column("") == {"raw": "", "cn": "", "en": ""}


def test_glossary_covers_every_normalized_daily_column() -> None:
    for column in (*DAILY_REQUIRED_COLUMNS, *DAILY_OPTIONAL_COLUMNS):
        assert column in EN_TO_CN


def test_eastmoney_rename_tables_are_unchanged_after_centralizing_the_glossary() -> None:
    assert EASTMONEY_DAILY_RENAME == {
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
        "换手率": "turnover",
        "流通股本": "outstanding_share",
    }
    assert EASTMONEY_SPOT_RENAME == {
        "代码": "code",
        "名称": "name",
        "今开": "open",
        "最高": "high",
        "最低": "low",
        "最新价": "close",
        "成交量": "volume",
        "成交额": "amount",
        "昨收": "prev_close",
        "涨跌幅": "pct",
        "涨跌额": "change",
    }
    assert EASTMONEY_MINUTE_RENAME == {
        "时间": "datetime",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "均价": "avg_price",
    }
    assert EASTMONEY_CAPITAL_FLOW_RENAME == {
        "日期": "date",
        "收盘价": "close",
        "涨跌幅": "pct_chg",
        "主力净流入-净额": "main_net_inflow",
        "主力净流入-净占比": "main_net_pct",
        "超大单净流入-净额": "super_large_net_inflow",
        "超大单净流入-净占比": "super_large_net_pct",
        "大单净流入-净额": "large_net_inflow",
        "大单净流入-净占比": "large_net_pct",
        "中单净流入-净额": "medium_net_inflow",
        "中单净流入-净占比": "medium_net_pct",
        "小单净流入-净额": "small_net_inflow",
        "小单净流入-净占比": "small_net_pct",
    }
