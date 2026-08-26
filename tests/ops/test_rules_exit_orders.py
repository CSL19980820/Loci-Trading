"""纸面监测退出单测：rules 全套档位 + AI 全权路径的止损兜底。"""
from __future__ import annotations

from src.ops.application.paper_exec import PaperOrder
from src.ops.application.rules_exit_orders import (
    position_exit_orders,
    rules_position_exit_orders,
    stop_loss_safety_net,
)


def _held(code: str = "600519", *, layers: float = 1.0, mark_cost: float = 100.0) -> dict:
    return {"code": code, "name": "茅台", "layers": layers, "mark_cost": mark_cost}


def test_rules_exit_stop_cut_on_mark_cost_loss() -> None:
    orders, note = rules_position_exit_orders(
        positions=[_held()],
        plan_items=[],
        quotes={"600519": {"price": 93.0, "name": "茅台"}},
        cfg={"stop_loss_pct": -6.0},
    )
    assert len(orders) == 1
    assert orders[0].action == "stop_cut"
    assert orders[0].layers == 1.0
    assert "止损" in note


def test_rules_exit_take_profit() -> None:
    orders, _ = rules_position_exit_orders(
        positions=[_held()],
        plan_items=[],
        quotes={"600519": {"price": 109.0, "name": "茅台"}},
        cfg={"stop_loss_pct": -6.0, "take_profit_pct": 8.0, "trim_high_min_pnl_pct": 3.0},
    )
    assert len(orders) == 1
    assert orders[0].action == "take_profit"


def test_rules_exit_trim_high_before_revise() -> None:
    orders, _ = rules_position_exit_orders(
        positions=[_held()],
        plan_items=[],
        quotes={"600519": {"price": 104.0, "name": "茅台"}},
        cfg={"stop_loss_pct": -6.0, "trim_high_min_pnl_pct": 3.0},
        stances=[
            {
                "code": "600519",
                "stance": "revise",
                "scenario": "gap_up",
                "reason": "高开偏离",
            }
        ],
    )
    assert len(orders) == 1
    assert orders[0].action == "trim_high"
    assert orders[0].layers == 0.5


def test_rules_exit_revise_gap_up_reduce() -> None:
    item = {
        "code": "600519",
        "name": "茅台",
        "ref_close": 100.0,
        "scenarios": {
            "gap_up": {
                "buy": True,
                "entry_pct_min": 0.5,
                "entry_pct_max": 2.0,
                "layers": 1.0,
            }
        },
        "auction": {"revise_allowed": True, "follow_requires_band": True},
    }
    orders, note = rules_position_exit_orders(
        positions=[_held()],
        plan_items=[item],
        quotes={"600519": {"price": 103.5, "prev_close": 100.0, "name": "茅台"}},
        cfg={"stop_loss_pct": -6.0, "trim_high_min_pnl_pct": 5.0},
        stances=[
            {
                "code": "600519",
                "stance": "revise",
                "scenario": "gap_up",
                "gap_pct": 3.5,
                "reason": "高开落在情景外",
            }
        ],
    )
    assert len(orders) == 1
    assert orders[0].action == "reduce"
    assert orders[0].layers == 0.5
    assert "revise" in note or "减仓" in note


def test_rules_exit_plan_item_stop_overrides_cfg() -> None:
    orders, _ = rules_position_exit_orders(
        positions=[_held(mark_cost=100.0)],
        plan_items=[{"code": "600519", "stop_loss_pct": -3.0}],
        quotes={"600519": {"price": 96.5, "name": "茅台"}},
        cfg={"stop_loss_pct": -8.0, "trim_high_min_pnl_pct": None},
    )
    assert len(orders) == 1
    assert orders[0].action == "stop_cut"


def test_rules_exit_disabled() -> None:
    orders, note = rules_position_exit_orders(
        positions=[_held()],
        plan_items=[],
        quotes={"600519": {"price": 90.0, "name": "茅台"}},
        cfg={"rules_exit_enabled": False, "stop_loss_pct": -6.0},
    )
    assert orders == []
    assert note == ""


def test_rules_exit_stop_wins_over_take_profit() -> None:
    """异常配置下仍优先止损。"""
    orders, _ = rules_position_exit_orders(
        positions=[_held()],
        plan_items=[],
        quotes={"600519": {"price": 93.0, "name": "茅台"}},
        cfg={"stop_loss_pct": -6.0, "take_profit_pct": 1.0},
    )
    assert len(orders) == 1
    assert orders[0].action == "stop_cut"


def test_safety_net_cuts_when_ai_is_silent() -> None:
    """模型失语（orders 为空）时，亏损仓仍必须被砍。"""
    orders, note = stop_loss_safety_net(
        existing=[],
        positions=[_held()],
        plan_items=[],
        quotes={"600519": {"price": 93.0, "name": "茅台"}},
        cfg={"stop_loss_pct": -6.0},
    )
    assert len(orders) == 1
    assert orders[0].action == "stop_cut"
    assert orders[0].decided_by == "rules"
    assert "兜底止损" in note


def test_safety_net_defers_to_ai_own_sell() -> None:
    """AI 已对该票出卖单时不重复叠加，避免同票两笔卖出。"""
    ai_order = PaperOrder(
        code="600519", action="reduce", layers=0.5, reason="AI 减仓", decided_by="ai"
    )
    orders, note = stop_loss_safety_net(
        existing=[ai_order],
        positions=[_held()],
        plan_items=[],
        quotes={"600519": {"price": 93.0, "name": "茅台"}},
        cfg={"stop_loss_pct": -6.0},
    )
    assert orders == []
    assert note == ""


def test_safety_net_ignores_ai_buy_on_same_code() -> None:
    """AI 在亏损票上加仓不算已处理，止损仍要触发。"""
    ai_order = PaperOrder(
        code="600519", action="add", layers=0.5, reason="AI 补仓", decided_by="ai"
    )
    orders, _ = stop_loss_safety_net(
        existing=[ai_order],
        positions=[_held()],
        plan_items=[],
        quotes={"600519": {"price": 93.0, "name": "茅台"}},
        cfg={"stop_loss_pct": -6.0},
    )
    assert len(orders) == 1
    assert orders[0].action == "stop_cut"


def test_safety_net_leaves_profit_taking_to_ai() -> None:
    """AI 路径只补止损，不替模型做止盈/高抛。"""
    orders, note = stop_loss_safety_net(
        existing=[],
        positions=[_held()],
        plan_items=[],
        quotes={"600519": {"price": 120.0, "name": "茅台"}},
        cfg={"stop_loss_pct": -6.0, "take_profit_pct": 8.0, "trim_high_min_pnl_pct": 3.0},
    )
    assert orders == []
    assert note == ""


def test_position_exit_dispatches_by_path() -> None:
    """同一持仓：rules 路径走全套（高抛），AI 路径只看止损。"""
    kwargs = {
        "existing": [],
        "positions": [_held()],
        "plan_items": [],
        "quotes": {"600519": {"price": 104.0, "name": "茅台"}},
        "cfg": {"stop_loss_pct": -6.0, "trim_high_min_pnl_pct": 3.0},
    }
    rules_orders, _ = position_exit_orders(**kwargs, ai_driven=False)
    ai_orders, _ = position_exit_orders(**kwargs, ai_driven=True)
    assert [o.action for o in rules_orders] == ["trim_high"]
    assert ai_orders == []


def test_position_exit_respects_disable_flag() -> None:
    orders, note = position_exit_orders(
        existing=[],
        positions=[_held()],
        plan_items=[],
        quotes={"600519": {"price": 90.0, "name": "茅台"}},
        cfg={"rules_exit_enabled": False, "stop_loss_pct": -6.0},
        ai_driven=True,
    )
    assert orders == []
    assert note == ""
