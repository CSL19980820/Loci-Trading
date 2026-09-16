"""涨停 momentum 扫描器：闸门 + 结构化候选。"""
from __future__ import annotations

from src.ops.application.skill_watch.limit_up_momentum import scan_limit_up_momentum
from src.ops.application.skill_watch.tuning import normalize_tuning


def _payload(rows: list[dict]) -> dict:
    return {"structured": {"rows": rows}}


def _strong_market_call_tool() -> object:
    def call_tool(name: str, arguments: dict) -> dict:
        if name == "short_term_emotion":
            return _payload([{"promotion_rate": 0.42, "broken_rate": 0.18}])
        if name == "limit_up_ladder":
            return _payload(
                [
                    {"code": "600001", "name": "前排龙", "level": 3, "pctChg": 10.0},
                    {"code": "600002", "name": "二板", "level": 2, "pctChg": 10.0},
                ]
            )
        if name == "theme_intraday_capital":
            return _payload(
                [{"themeCode": "801843k", "themeName": "机器人", "strength": 82}]
            )
        if name == "broken_limit_up":
            return _payload([{"code": "600003", "name": "弱转强", "pctChg": 2.5}])
        if name == "auction_opening_snapshot":
            return _payload({"rows": []})
        raise AssertionError(name)

    return call_tool


def test_limit_up_momentum_emits_structured_paper_candidate() -> None:
    result = scan_limit_up_momentum(_strong_market_call_tool())

    assert result["market_gate"]["state"] == "dragon"
    assert result["picks"]
    assert result["picks"][0]["validation"] == "unverified"
    assert result["picks"][0]["code"] == "600001"
    assert any(signal["type"] == "paper_candidate" for signal in result["signals"])


def test_empty_gate_emits_watch_only_without_picks() -> None:
    def call_tool(name: str, arguments: dict) -> dict:
        if name == "short_term_emotion":
            return _payload([{"promotion_rate": 0.12, "broken_rate": 0.55}])
        if name == "limit_up_ladder":
            return _payload([{"code": "600001", "name": "孤板", "level": 1, "pctChg": 10.0}])
        if name == "theme_intraday_capital":
            return _payload([{"themeName": "冷门", "strength": 20}])
        if name == "broken_limit_up":
            return _payload([])
        raise AssertionError(name)

    result = scan_limit_up_momentum(call_tool)

    assert result["market_gate"]["state"] == "empty"
    assert result["picks"] == []
    assert any(signal["type"] == "gate_empty" for signal in result["signals"])


def test_paper_candidates_stage_off_skips_picks() -> None:
    tuning = normalize_tuning({"stages": {"paper_candidates": False}})
    result = scan_limit_up_momentum(_strong_market_call_tool(), tuning=tuning)

    assert result["picks"] == []
    assert any("纸面候选已关闭" in str(s.get("reason")) for s in result["signals"])
