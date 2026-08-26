"""纸面量化：下单动作矩阵、仓位层数、告警规则与次日场景闸门。

日终复盘在 `test_paper_eod_review.py`，次日预案落地在 `test_paper_nextday.py`。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.ops.application.nextday_plan import (
    classify_open_scenario,
    enrich_plan_items,
    evaluate_auction_stance,
    merge_ai_orders_with_gates,
    scenario_gated_open_orders,
    session_clock,
)
from src.ops.application.notify_policy import NotifyPolicy
from src.ops.application.paper_exec import (
    PaperOrder,
    apply_order_to_positions,
    execute_orders,
    validate_and_normalize_order,
)
from src.ops.infrastructure.store import OpsStore


def test_notify_quiet_hours_cross_midnight() -> None:
    policy = NotifyPolicy(timezone="Asia/Shanghai", quiet_hours="23:00-07:00")
    quiet = datetime.fromisoformat("2026-08-06T23:30:00+08:00")
    awake = datetime.fromisoformat("2026-08-06T10:00:00+08:00")
    assert policy.is_quiet_now(quiet) is True
    assert policy.is_quiet_now(awake) is False


def test_paper_action_matrix_open_trim_buy_dip_close(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.ensure_paper_cabin("demo", max_layers=4.0)
        quotes = {"600519": {"price": 100.0, "name": "茅台", "high": 105.0}}
        r1 = execute_orders(
            store,
            slug="demo",
            orders=[PaperOrder(code="600519", action="open", layers=1.0, reason="开仓")],
            quotes=quotes,
            source="test",
        )
        assert len(r1.fills) == 1
        assert r1.positions[0]["layers"] == 1.0

        quotes["600519"]["price"] = 110.0
        r2 = execute_orders(
            store,
            slug="demo",
            orders=[PaperOrder(code="600519", action="trim_high", layers=0.5, reason="高抛")],
            quotes=quotes,
            source="test",
            trim_high_min_pnl_pct=3.0,
        )
        assert len(r2.fills) == 1
        assert r2.positions[0]["layers"] == 0.5

        quotes["600519"]["price"] = 100.0
        r3 = execute_orders(
            store,
            slug="demo",
            orders=[PaperOrder(code="600519", action="buy_dip", layers=0.5, reason="低吸")],
            quotes=quotes,
            source="test",
            buy_dip_drawdown_pct=2.0,
        )
        assert len(r3.fills) == 1
        assert abs(r3.positions[0]["layers"] - 1.0) < 1e-6

        r4 = execute_orders(
            store,
            slug="demo",
            orders=[PaperOrder(code="600519", action="take_profit", layers=1.0, reason="止盈")],
            quotes=quotes,
            source="test",
        )
        assert len(r4.fills) == 1
        assert r4.positions == []


def test_dragon_cabin_rejects_fourth_position(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.ensure_paper_cabin("dragon-return")
        quotes = {
            code: {"price": 10.0, "name": code}
            for code in ("600001", "300001", "600002", "300002")
        }
        first = execute_orders(
            store,
            slug="dragon-return",
            orders=[
                PaperOrder(code=code, action="open", layers=1.0, reason="开仓")
                for code in ("600001", "300001", "600002")
            ],
            quotes=quotes,
            source="test",
        )
        fourth = execute_orders(
            store,
            slug="dragon-return",
            orders=[PaperOrder(code="300002", action="open", layers=1.0, reason="第四只")],
            quotes=quotes,
            source="test",
        )

        assert len(first.positions) == 3
        assert fourth.fills == []
        assert fourth.rejects[0]["reason"] == "持股已达 3 只上限"
        cabin = store.get_paper_cabin("dragon-return") or {}
        assert cabin["max_layers"] == 10.0
        assert cabin["config"]["initial_capital"] == 200_000.0


def test_paper_reject_invalid_layer_and_no_position_trim(tmp_path: Path) -> None:
    positions: list[dict] = []
    order, reason = validate_and_normalize_order(
        PaperOrder(code="600519", action="open", layers=0.3, mark_price=10),
        positions=positions,
        max_layers=4,
    )
    assert order is None and reason

    order2, reason2 = validate_and_normalize_order(
        PaperOrder(code="600519", action="trim_high", layers=0.5, mark_price=10),
        positions=positions,
        max_layers=4,
    )
    assert order2 is None and reason2


def test_apply_order_avg_cost() -> None:
    positions = [{"code": "1", "name": "a", "layers": 1.0, "mark_cost": 10.0}]
    next_pos = apply_order_to_positions(
        positions,
        PaperOrder(code="1", action="add", layers=1.0, mark_price=12.0, name="a"),
    )
    assert abs(next_pos[0]["layers"] - 2.0) < 1e-9
    assert abs(next_pos[0]["mark_cost"] - 11.0) < 1e-9


def test_paper_reduce_stop_cut_hold_and_close(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.ensure_paper_cabin("demo", max_layers=4.0)
        quotes = {"600519": {"price": 100.0, "name": "茅台"}}
        execute_orders(
            store,
            slug="demo",
            orders=[PaperOrder(code="600519", action="open", layers=2.0, reason="开")],
            quotes=quotes,
            source="test",
        )
        r_hold = execute_orders(
            store,
            slug="demo",
            orders=[PaperOrder(code="600519", action="hold", layers=0, reason="观望")],
            quotes=quotes,
            source="test",
        )
        assert r_hold.fills == [] and r_hold.rejects == []

        r_reduce = execute_orders(
            store,
            slug="demo",
            orders=[PaperOrder(code="600519", action="reduce", layers=0.5, reason="减")],
            quotes=quotes,
            source="test",
        )
        assert abs(r_reduce.positions[0]["layers"] - 1.5) < 1e-6

        quotes["600519"]["price"] = 90.0
        r_cut = execute_orders(
            store,
            slug="demo",
            orders=[PaperOrder(code="600519", action="stop_cut", layers=0.5, reason="止损")],
            quotes=quotes,
            source="test",
        )
        assert abs(r_cut.positions[0]["layers"] - 1.0) < 1e-6

        r_close = execute_orders(
            store,
            slug="demo",
            orders=[PaperOrder(code="600519", action="close", layers=0, reason="清仓")],
            quotes=quotes,
            source="test",
        )
        assert r_close.positions == []


def test_alert_rule_persist_and_scan_dry(tmp_path: Path, monkeypatch) -> None:
    from src.ops.application import alert_rules as ar

    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.upsert_alert_rule(
            {
                "code": "600519",
                "name": "茅台提醒",
                "condition_group": {
                    "op": "and",
                    "conditions": [{"type": "price", "op": ">=", "value": 10}],
                },
            }
        )

        def fake_quotes(codes, *, force_refresh=False):
            return (
                {"600519": {"code": "600519", "price": 20.0, "name": "茅台"}},
                {"600519": "test"},
                {"600519": False},
            )

        monkeypatch.setattr(ar, "get_cached_quotes", fake_quotes)
        result = ar.scan_alert_rules(store, dry_run=True)
        assert result["triggered"] == 1

def test_scenario_plan_high_flat_low_and_auction_gate() -> None:
    items = enrich_plan_items(
        [{"code": "600519", "name": "茅台", "layers": 1.0, "ref_close": 100.0, "thesis": "试盘"}],
        gap_up_chase=False,
        entry_mode="scenario",
    )
    assert items[0]["scenarios"]["gap_up"]["buy"] is False
    assert items[0]["scenarios"]["flat"]["buy"] is True
    assert items[0]["scenarios"]["gap_down"]["buy"] is True

    assert classify_open_scenario(ref_close=100, live_price=102, flat_band_pct=0.5)[0] == "gap_up"
    assert classify_open_scenario(ref_close=100, live_price=100.2, flat_band_pct=0.5)[0] == "flat"
    assert classify_open_scenario(ref_close=100, live_price=97, flat_band_pct=0.5)[0] == "gap_down"

    abandon = evaluate_auction_stance(items[0], {"price": 102.0, "prev_close": 100.0})
    assert abandon["stance"] == "abandon"

    follow_flat = evaluate_auction_stance(items[0], {"price": 100.2, "prev_close": 100.0})
    assert follow_flat["stance"] == "follow"

    auction = session_clock(
        datetime(2026, 8, 7, 9, 20, tzinfo=ZoneInfo("Asia/Shanghai")),
        auction_allow_open=False,
    )
    assert auction.in_auction is True
    orders, decisions, note = scenario_gated_open_orders(
        plan_items=items,
        positions=[],
        quotes={"600519": {"price": 100.2, "prev_close": 100.0}},
        clock=auction,
        stances=[follow_flat],
    )
    assert orders == []
    assert "09:15-09:30" in note or "竞价" in note
    assert decisions[0]["stance"] == "follow"

    open_clock = session_clock(
        datetime(2026, 8, 7, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    orders2, _, _ = scenario_gated_open_orders(
        plan_items=items,
        positions=[],
        quotes={"600519": {"price": 100.2, "prev_close": 100.0}},
        clock=open_clock,
        stances=[follow_flat],
    )
    assert len(orders2) == 1 and orders2[0].action == "open"

    kept, rejects = merge_ai_orders_with_gates(
        [PaperOrder(code="600519", action="open", layers=1.0, reason="AI硬开")],
        plan_items=items,
        quotes={"600519": {"price": 103.0, "prev_close": 100.0}},
        clock=open_clock,
    )
    assert kept == []
    assert rejects and "情景门闩" in str(rejects[0]["reason"])


def test_generate_nextday_plan_writes_scenarios(tmp_path: Path) -> None:
    from src.ops.application.jobs.paper_quant import generate_nextday_plan

    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        plan = generate_nextday_plan(
            store,
            slug="demo",
            picks=[{"code": "600519", "name": "茅台", "close": 100, "reason": "尾盘强"}],
            source="test",
            notify=False,
        )
        assert plan["items"][0]["scenarios"]["flat"]["buy"] is True
        assert "高开" in plan["body_text"]
        assert "竞价纠偏" in plan["body_text"]
        assert plan["config_snapshot"]["auction_window"] == "09:15-09:30"
        assert "【次日情景预案】" in plan["plan_section"]


def test_nextday_plan_push_is_plan_section_only(tmp_path: Path, monkeypatch) -> None:
    """企微只推情景段，不把风格记忆/子图塞进推送。"""
    from src.ops.application.jobs import paper_quant_plan as plan_mod

    pushed: list[dict[str, str]] = []

    def _fake_dispatch(store, *, title, body, **_k):
        pushed.append({"title": title, "body": body})
        return {"sent": ["wecom"]}

    monkeypatch.setattr(plan_mod, "dispatch_text", _fake_dispatch)
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.ensure_paper_cabin("dragon-return", config={"follow_wecom": True})
        plan = plan_mod.generate_nextday_plan(
            store,
            slug="dragon-return",
            picks=[{"code": "600519", "name": "茅台", "close": 100}],
            source="screen",
            body_text="【日终总结】不该出现在推送里",
            notify=True,
        )
        # 默认不注入风格人设；推送正文只有情景段
        assert "日终总结" in plan["body_text"]
        assert "交易风格" not in plan["body_text"]
        assert len(pushed) == 1
        assert "次日预案" in pushed[0]["title"]
        assert "【次日情景预案】龙王" in pushed[0]["body"]
        assert "dragon-return" not in pushed[0]["body"]
        assert "日终总结" not in pushed[0]["body"]
        assert "交易风格" not in pushed[0]["body"]


def test_paper_eod_one_review_push_with_nextday_plan(tmp_path: Path, monkeypatch) -> None:
    """盘后只推一条复盘，正文合并日终与次日预案且不露英文 slug。"""
    from src.ops.application.jobs import paper_quant_eod as eod_mod
    from src.ops.application.jobs import paper_quant_plan as plan_mod
    from src.ops.application.jobs import paper_quant_support as pq_support

    pushed: list[dict[str, str]] = []

    def _fake_dispatch(store, *, title, body, **_k):
        pushed.append({"title": title, "body": body})
        return {"sent": ["wecom"]}

    monkeypatch.setattr(eod_mod, "dispatch_text", _fake_dispatch)
    monkeypatch.setattr(plan_mod, "dispatch_text", _fake_dispatch)
    monkeypatch.setattr(pq_support, "_today", lambda: "2026-08-07")
    monkeypatch.setattr(pq_support, "_next_trade_date", lambda *_a, **_k: "2026-08-10")
    monkeypatch.setattr(
        pq_support,
        "resolve_trading_day_gate",
        lambda *a, **k: {
            "trade_date": "2026-08-07",
            "is_trading_day": True,
            "last_trading_day": "2026-08-07",
            "calendar_source": "test",
            "buy_execution_allowed": True,
            "note": "test",
        },
    )
    monkeypatch.setattr(
        "src.ops.application.paper_style_memory.run_eod_learning",
        lambda *a, **k: {
            "critique": "",
            "lookback_digest": "【五日回看】池内 0 · 买过 0 · 错过 0 · 新入池 0 · 卖过 0",
            "lessons": [],
            "absorbed": 0,
            "style": {},
            "lookback": None,
            "persist_memory": False,
        },
    )
    monkeypatch.setattr(
        eod_mod,
        "_nextday_picks_after_eod",
        lambda *a, **k: (
            [{"code": "600519", "name": "茅台", "close": 100, "reason": "回踩确认"}],
            {},
        ),
    )

    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.ensure_paper_cabin("dragon-return", config={"follow_wecom": True})
        from src.ops.application.jobs.context import JobContext

        result = eod_mod.execute_paper_eod(
            {"slug": "dragon-return", "push": True},
            JobContext(ops_store=store),
        )

    assert len(pushed) == 1 and result["notify"] == {"sent": ["wecom"]}
    assert pushed[0]["title"] == "盘后复盘·龙回头"
    assert "【日终总结】龙回头" in pushed[0]["body"]
    assert "dragon-return" not in pushed[0]["body"]
    assert "【次日情景预案】龙王" in pushed[0]["body"]
    assert "五日回看" in pushed[0]["body"]
    assert "评头论足" not in pushed[0]["body"]
    assert "交易风格" not in pushed[0]["body"]
    assert "记忆子图" not in pushed[0]["body"]
    assert "成交额 暂无" not in pushed[0]["body"]


def test_format_plan_body_is_compact_zh() -> None:
    from src.ops.application.plan_build import format_plan_body

    text = format_plan_body(
        "dragon-return",
        "2026-08-10",
        [
            {
                "code": "600519",
                "name": "茅台",
                "ref_close": 100,
                "intent": "buy",
                "thesis": "回踩五日线后的二次确认再接",
                "entry_mode": "next_open",
                "scenarios": {
                    "gap_up": {
                        "buy": False,
                        "entry_pct_min": 1.5,
                        "entry_pct_max": 3.0,
                        "layers": 1,
                    },
                    "flat": {
                        "buy": True,
                        "entry_pct_min": -0.5,
                        "entry_pct_max": 0.8,
                        "layers": 2,
                    },
                    "gap_down": {
                        "buy": True,
                        "entry_pct_min": -2.5,
                        "entry_pct_max": -1.0,
                        "layers": 2,
                        "layers_if_stretched": 1,
                    },
                },
            },
            {
                "code": "600001",
                "name": "观察龙",
                "intent": "observe",
                "role_label": "龙头",
                "score": 58,
            },
        ],
        observe_changes={
            "kept": [{"code": "600002", "name": "旧票"}],
            "added": [
                {
                    "code": "600001",
                    "name": "观察龙",
                    "reason": "龙头·58分·未达可买线",
                }
            ],
            "replaced": [],
            "dropped": [],
            "changed": True,
        },
    )
    assert "龙王" in text
    assert "观察池变更" in text
    assert "新进观察 观察龙" in text
    assert "续盯" in text
    assert "🛒【可买】" in text
    assert "👀【观察】" in text
    assert "1、👀 观察龙 600001，58分，🐲，仅观察" in text
    assert "今日入池" not in text
    assert "dragon-return" not in text
    assert "next_open" not in text
    assert "｜" in text
