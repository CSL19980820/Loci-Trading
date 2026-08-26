"""P0-1：AI 纸面 add/buy_dip 必须与 open 同等过情景门闩。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.ops.application.nextday_plan import (
    enrich_plan_items,
    merge_ai_orders_with_gates,
    session_clock,
)
from src.ops.application.paper_exec import PaperOrder


def test_merge_ai_orders_blocks_add_and_buy_dip_when_stance_not_follow() -> None:
    items = enrich_plan_items(
        [{"code": "600519", "name": "茅台", "close": 100, "reason": "测试"}]
    )
    clock = session_clock(
        now=datetime(2026, 8, 7, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    quotes = {"600519": {"price": 103.0, "prev_close": 100.0}}  # 高开 → abandon
    for action in ("add", "buy_dip", "open"):
        kept, rejects = merge_ai_orders_with_gates(
            [PaperOrder(code="600519", action=action, layers=0.5, reason="AI绕门")],
            plan_items=items,
            quotes=quotes,
            clock=clock,
        )
        assert kept == [], action
        assert rejects and "情景门闩" in str(rejects[0]["reason"]), action


def test_merge_ai_orders_blocks_add_when_scan_abandoned() -> None:
    items = [
        {
            "code": "600001",
            "name": "放弃龙",
            "ref_close": 10.0,
            "auction_stance": "abandoned",
            "auction_reason": "竞价砸盘",
            "scenarios": {
                "gap_up": {"buy": False, "entry_pct_min": 0.5, "entry_pct_max": 3, "layers": 0.5},
                "flat": {"buy": True, "entry_pct_min": -0.5, "entry_pct_max": 0.5, "layers": 0.5},
                "gap_down": {"buy": True, "entry_pct_min": -4, "entry_pct_max": -0.5, "layers": 0.5},
            },
            "auction": {"follow_requires_band": True, "revise_allowed": True},
        }
    ]
    clock = session_clock(
        now=datetime(2026, 8, 7, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    kept, rejects = merge_ai_orders_with_gates(
        [PaperOrder(code="600001", action="add", layers=0.5, reason="AI加仓")],
        plan_items=items,
        quotes={"600001": {"price": 10.0, "prev_close": 10.0}},
        clock=clock,
    )
    assert kept == []
    assert rejects and "扫描竞价放弃" in str(rejects[0]["reason"])
