"""纸面候选竞价门闩过滤。"""
from __future__ import annotations

from src.ops.application.nextday_plan import (
    enrich_plan_items,
    scenario_gated_open_orders,
    session_clock,
)
from src.ops.application.skill_watch.paper_eligibility import (
    filter_openable_picks,
    is_auction_abandoned,
    scan_auction_block_reason,
)


def test_abandoned_pick_is_not_openable() -> None:
    pick = {
        "code": "600001",
        "name": "砸盘龙",
        "auction_stance": "abandoned",
        "auction_reason": "竞价低开 -8%，龙头逻辑破坏",
    }
    assert is_auction_abandoned(pick) is True
    openable, excluded = filter_openable_picks([pick])
    assert openable == []
    assert excluded == [pick]


def test_pending_pick_is_not_openable() -> None:
    pick = {
        "code": "600004",
        "name": "待定龙",
        "auction_stance": "pending",
        "auction_reason": "竞价数据未就绪",
    }
    assert is_auction_abandoned(pick) is True
    openable, excluded = filter_openable_picks([pick])
    assert openable == []
    assert excluded == [pick]
    assert "待定" in (scan_auction_block_reason(pick) or "")


def test_abandon_alias_is_not_openable() -> None:
    pick = {"code": "600005", "auction_stance": "abandon"}
    assert is_auction_abandoned(pick) is True


def test_failed_role_without_stance_is_not_blocked_by_chinese_heuristic() -> None:
    """判废只认 auction_stance / open_blocked，不再解析中文 role_basis。"""
    pick = {
        "code": "600002",
        "role": "failed",
        "role_basis": "竞价放弃：承接转弱",
    }
    assert is_auction_abandoned(pick) is False
    assert scan_auction_block_reason(pick) is None


def test_failed_role_with_abandoned_stance_is_blocked() -> None:
    pick = {
        "code": "600002",
        "role": "failed",
        "auction_stance": "abandoned",
        "auction_reason": "竞价放弃：承接转弱",
        "role_basis": "竞价放弃：承接转弱",
    }
    assert is_auction_abandoned(pick) is True
    assert scan_auction_block_reason(pick) == "扫描竞价放弃：竞价放弃：承接转弱"


def test_downgraded_pick_stays_but_is_conservative() -> None:
    pick = {
        "code": "600003",
        "name": "弱龙",
        "planned_layers": 1.0,
        "auction_stance": "downgraded",
    }
    openable, excluded = filter_openable_picks([pick])
    assert excluded == []
    assert openable[0]["planned_layers"] == 0.5
    assert openable[0]["auction"]["downgraded"] is True

    items = enrich_plan_items(openable, entry_mode="scenario")
    assert items[0]["planned_layers_max"] == 0.5
    assert items[0]["scenarios"]["gap_up"]["buy"] is False


def test_downgrade_reads_planned_layers_max_first() -> None:
    pick = {
        "code": "600006",
        "name": "双键",
        "layers": 1.0,
        "planned_layers": 1.5,
        "planned_layers_max": 2.0,
        "auction_stance": "downgraded",
    }
    openable, _ = filter_openable_picks([pick])
    assert openable[0]["planned_layers"] == 0.5
    items = enrich_plan_items(openable, entry_mode="scenario")
    assert items[0]["planned_layers_max"] == 0.5


def test_downgrade_thesis_is_idempotent_on_reentry() -> None:
    """P1-4：auction.downgraded 幂等，thesis 不因三次 filter 重复追加。"""
    from src.ops.application.paper_policy.eligibility import apply_downgrade_conservative

    pick = {
        "code": "600007",
        "name": "三重",
        "planned_layers": 1.0,
        "auction_stance": "downgraded",
        "thesis": "回踩确认",
    }
    once = apply_downgrade_conservative(pick)
    twice = apply_downgrade_conservative(once)
    thrice = apply_downgrade_conservative(twice)
    note = "竞价降级：仅半层、高开不追"
    assert thrice["thesis"].count(note) == 1
    assert thrice is twice or thrice["thesis"] == twice["thesis"]


def test_scenario_gate_hard_rejects_scan_abandoned_plan_item() -> None:
    items = enrich_plan_items(
        [
            {
                "code": "600001",
                "name": "放弃龙",
                "ref_close": 10.0,
                "auction_stance": "abandoned",
                "auction_reason": "竞价砸盘",
            }
        ]
    )
    assert items == []

    legacy_item = {
        "code": "600002",
        "name": "旧预案",
        "ref_close": 10.0,
        "role": "failed",
        "auction_stance": "abandoned",
        "auction_reason": "竞价放弃",
        "role_basis": "竞价放弃",
        "scenarios": {
            "gap_up": {"buy": False, "entry_pct_min": 0.5, "entry_pct_max": 3, "layers": 0.5},
            "flat": {"buy": True, "entry_pct_min": -0.5, "entry_pct_max": 0.5, "layers": 0.5},
            "gap_down": {"buy": True, "entry_pct_min": -4, "entry_pct_max": -0.5, "layers": 0.5},
        },
        "auction": {"follow_requires_band": True, "revise_allowed": True},
    }
    clock = session_clock(
        now=__import__("datetime").datetime(2026, 8, 7, 10, 0, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai"))
    )
    orders, decisions, note = scenario_gated_open_orders(
        plan_items=[legacy_item],
        positions=[],
        quotes={"600002": {"price": 10.0, "prev_close": 10.0}},
        clock=clock,
    )
    assert orders == []
    assert decisions[0]["stance"] == "abandon"
    assert "扫描竞价放弃" in decisions[0]["reason"]
    assert "放弃" in note or orders == []


def test_has_actionable_picks_skips_observe_only() -> None:
    from src.ops.application.skill_watch.paper_eligibility import has_actionable_picks

    assert has_actionable_picks([]) is False
    assert has_actionable_picks(
        [{"code": "001258", "name": "立新能源", "intent": "observe", "score": 82}]
    ) is False
    assert has_actionable_picks(
        [{"code": "600000", "name": "测试", "intent": "buy", "score": 80}]
    ) is True
    assert has_actionable_picks([{"code": "600000", "name": "测试", "score": 80}]) is True
