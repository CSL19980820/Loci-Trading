"""解析失败不许伪装成「今天没有数据」。

悟道正文超限会被 MCP 客户端截断，截断后 JSON 必然解析不出结构化段。若此时
把信封本身当数据返回，``extract_freshness`` 会从信封里的 ``quota.trade_date``
挖出一个「今天」——扫描器于是拿到一份「今日、未降级、零行」的结果，把取数
故障读成市场真的没货。
"""
from __future__ import annotations

from src.ops.application.skill_watch.payload import extract_freshness, structured


def _envelope(**overrides) -> dict[str, object]:
    """还原 call_mcp_tool 的真实返回体形状。"""
    payload = {
        "tool": "short_term_emotion",
        "arguments": {"tradeDate": "2026-08-07"},
        "server": "wudao",
        "text": '{"limitUpCount": 31, "temperat',
        "is_error": False,
        "structured": None,
        "truncated": True,
        "quota": {
            "trade_date": "2026-08-11",
            "used": {"structured": 12, "skill": 0, "total": 12},
        },
    }
    payload.update(overrides)
    return payload


def test_truncated_envelope_yields_no_structured_section() -> None:
    assert structured(_envelope()) == {}


def test_quota_trade_date_is_not_mistaken_for_the_market_trade_date() -> None:
    """信封里的 quota.trade_date 是配额计数的日历日，不是行情交易日。"""
    freshness = extract_freshness(_envelope(), requested="2026-08-07")

    assert not freshness.get("actual_trade_date")


def test_a_real_structured_section_still_parses() -> None:
    payload = _envelope(
        structured={"actualTradeDate": "2026-08-07", "limitUpCount": 31},
        text="",
        truncated=False,
    )

    assert structured(payload)["limitUpCount"] == 31
    assert extract_freshness(payload, requested="2026-08-07")["actual_trade_date"] == (
        "2026-08-07"
    )


def test_json_text_still_parses_when_it_is_intact() -> None:
    payload = _envelope(text='{"actualTradeDate": "2026-08-07", "limitUpCount": 31}')

    assert structured(payload)["limitUpCount"] == 31


def test_a_bare_structured_dict_is_still_accepted() -> None:
    """调用方直接传解析好的段落时不能被当成信封丢掉。"""
    bare = {"actualTradeDate": "2026-08-07", "limitUpCount": 31}

    assert structured(bare) == bare
