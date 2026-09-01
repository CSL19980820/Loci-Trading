"""preset 解析：静态篮子、排行榜排序、硬上限。外部 HTTP 全部注入假实现。"""
from __future__ import annotations

import pytest

from src.market.application.watchlist import (
    ALL_PRESETS,
    INDEX_BASKET,
    MAX_PRESET_CODES,
WatchlistError,
    list_watchlist_presets,
    movers_universe,
    resolve_preset,
)


def _row(code: str, *, pct: float = 0.0, turnover: float = 0.0, amount: float = 0.0):
    return {
        "code": code,
        "name": f"票{code}",
        "price": 10.0,
        "prev_close": 10.0,
        "pct": pct,
        "turnover": turnover,
        "amount": amount,
    }


def _cross_section(count: int):
    """假的东财全市场截面：涨幅从高到低，成交额从低到高。"""

    def fetch():
        return [
            _row(f"{600000 + i:06d}", pct=float(count - i), turnover=float(i), amount=float(i))
            for i in range(count)
        ]

    return fetch


def test_index_preset_is_static_and_typed_as_index() -> None:
    resolved = resolve_preset("index")
    assert resolved.kind == "static"
    assert resolved.source == "static_index"
    assert resolved.codes == [code for code, _label in INDEX_BASKET]
    assert set(resolved.instrument_types.values()) == {"INDEX"}
    # 指数不在东财 spot 表里，解析阶段不该带回任何行。
    assert resolved.rows == []


def test_ranked_preset_returns_rows_so_the_hub_fetches_once() -> None:
    resolved = resolve_preset("gainers", top_n=5, cross_section=_cross_section(50))
    assert resolved.kind == "ranked"
    assert resolved.source == "eastmoney_spot"
    assert len(resolved.codes) == 5
    # 排序用的截面表本身就是报价：行必须原样带回，否则 hub 会再打一次上游。
    assert [row["code"] for row in resolved.rows] == resolved.codes
    assert [row["pct"] for row in resolved.rows] == sorted(
        [row["pct"] for row in resolved.rows], reverse=True
    )


def test_losers_sorts_ascending() -> None:
    resolved = resolve_preset("losers", top_n=3, cross_section=_cross_section(20))
    pcts = [row["pct"] for row in resolved.rows]
    assert pcts == sorted(pcts)
    assert pcts[0] == 1.0


@pytest.mark.parametrize("preset", ["turnover", "amount"])
def test_ranked_presets_use_their_own_sort_key(preset: str) -> None:
    resolved = resolve_preset(preset, top_n=4, cross_section=_cross_section(30))
    values = [row[preset] for row in resolved.rows]
    assert values == sorted(values, reverse=True)


def test_ranked_preset_respects_hard_cap_even_when_top_n_is_huge() -> None:
    resolved = resolve_preset("gainers", top_n=5000, cross_section=_cross_section(900))
    assert len(resolved.codes) == MAX_PRESET_CODES
    assert len(resolved.rows) == MAX_PRESET_CODES
    assert resolved.truncated is True


def test_watchlist_preset_caps_and_drops_invalid_codes() -> None:
    codes = [f"{600000 + i:06d}" for i in range(MAX_PRESET_CODES + 50)]
    resolved = resolve_preset("watchlist", ["", "  ", "not-a-code", *codes])
    assert len(resolved.codes) == MAX_PRESET_CODES
    assert resolved.truncated is True
    assert set(resolved.instrument_types.values()) == {"STOCK"}


def test_watchlist_preset_dedupes() -> None:
    resolved = resolve_preset("watchlist", ["600000", "600000", "000001"])
    assert resolved.codes == ["600000", "000001"]


def test_watchlist_preset_without_codes_is_an_error() -> None:
    with pytest.raises(WatchlistError):
        resolve_preset("watchlist", [])


def test_unknown_preset_is_an_error() -> None:
    with pytest.raises(WatchlistError):
        resolve_preset("moon-phase")


def test_ranked_preset_can_be_filtered_by_explicit_codes() -> None:
    resolved = resolve_preset(
        "gainers", ["600003", "600007"], top_n=50, cross_section=_cross_section(20)
    )
    assert set(resolved.codes) == {"600003", "600007"}


def test_preset_catalog_covers_every_preset() -> None:
    listed = {item["id"] for item in list_watchlist_presets()}
    assert listed == set(ALL_PRESETS)


def _code_ordered_section(count: int):
    """贴着真实上游的假截面：**按代码倒序**返回（``fid=f12`` + ``po=1``），
    而真正在动的票（涨停 / 巨量）是代码最小的那几只。
    """

    def fetch():
        rows = [
            _row(f"{600000 + i:06d}", pct=-float(i), turnover=0.0, amount=0.0)
            for i in range(count)
        ]
        rows[0]["pct"], rows[0]["amount"] = 9.9, 1e9   # 今日领涨 + 天量
        rows[1]["turnover"] = 45.0      # 今日换手王
        return sorted(rows, key=lambda row: row["code"], reverse=True)

    return fetch


def test_signals_universe_is_the_movers_not_the_head_of_the_table() -> None:
    """**「盯盘大屏一整天零信号」的回归钉**。

    旧实现是 ``rows[:400]``：上游按代码倒序发表，于是信号池永远是代码最大的
    那 400 只（清一色北交所），涨停就在屏幕上而信号栏一条不出。
    """
    resolved = resolve_preset("signals", cross_section=_code_ordered_section(900))
    assert len(resolved.codes) == MAX_PRESET_CODES
    # 领涨 / 天量 / 换手王三只都必须在池子里
    assert "600000" in resolved.codes
    assert "600001" in resolved.codes
    # 而不是简单地把表头 400 行端过来
    head = [row["code"] for row in _code_ordered_section(900)()][:MAX_PRESET_CODES]
    assert resolved.codes != head
    # 信号池不含指数：「临近涨停」放在指数上没有意义
    assert resolved.index_codes == []


def test_all_preset_carries_index_codes_for_the_board_strip() -> None:
    """指数不在东财截面里；不把篮子交出去，大屏的指数带就只能停在首屏快照。"""
    resolved = resolve_preset("all", cross_section=_code_ordered_section(900))
    assert resolved.index_codes == [code for code, _label in INDEX_BASKET]
    assert "600000" in resolved.codes
    assert len(resolved.codes) == MAX_PRESET_CODES


def test_movers_universe_dedupes_and_caps() -> None:
    rows = [_row(f"{600000 + i:06d}", pct=float(i), amount=float(i)) for i in range(50)]
    picked = movers_universe(rows, limit=10)
    assert len(picked) == 10
    assert len({row["code"] for row in picked}) == 10
