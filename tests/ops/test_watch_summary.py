"""监测推送正文：紧凑一行、时效提示、无英文伪码。"""
from __future__ import annotations

from src.ops.application.skill_watch.watch_summary import format_watch_summary


def test_empty_degraded_gate_is_one_compact_line() -> None:
    text = format_watch_summary(
        skill_name="龙回头·龙空龙实战战法",
        slug="dragon-return",
        trade_date="2026-08-07",
        gate={
            "state": "empty",
            "mode": "空",
            "label": "空仓窗口",
            "data_status": "degraded",
            "missing": ["promotion_rate", "theme_strength"],
            "reasons": ["关键数据不完整，按空仓处理", "炸板率偏高", "梯队有高度"],
            "freshness": {
                "actual_trade_date": "2026-08-07",
                "snapshot_time": "2026-08-07T03:02:02.655Z",
                "stale": False,
            },
        },
        signals=[
            {
                "type": "gate_empty",
                "code": "market",
                "reason": "关键数据不完整，按空仓处理；炸板率偏高；梯队有高度",
            }
        ],
    )
    assert "📅08-07" in text
    assert "🛑空仓" in text
    assert "缺：晋级率、主线强度" in text
    assert "已见：炸板率偏高；梯队有高度" in text
    assert "→不扩仓" in text
    # 主结论压在一行
    assert text.count("\n") == 0
    assert "gate_empty" not in text
    assert "龙空龙实战战法" not in text
    assert "market" not in text.lower()


def test_stale_data_marked_not_realtime() -> None:
    text = format_watch_summary(
        skill_name="龙头地图",
        slug="market-leader-map",
        trade_date="2026-08-07",
        gate={
            "state": "empty",
            "data_status": "degraded",
            "reasons": ["数据非当日实时，按空仓处理", "晋级率低"],
            "freshness": {
                "actual_trade_date": "2026-08-06",
                "stale": True,
                "notes": ["非当日"],
            },
        },
    )
    assert "非实时" in text or "非当日" in text
    assert "依据：晋级率低" in text
    assert "\n" not in text


def test_attack_gate_lists_picks_in_chinese() -> None:
    text = format_watch_summary(
        skill_name="龙回头",
        slug="dragon-return",
        trade_date="2026-08-07",
        gate={
            "state": "dragon",
            "reasons": ["晋级率支持", "梯队有高度"],
            "freshness": {
                "actual_trade_date": "2026-08-07",
                "snapshot_time": "2026-08-07T03:10:00Z",
            },
        },
        picks=[
            {
                "code": "600721",
                "name": "百花医药",
                "role": "leader",
                "score": 88,
                "intent": "buy",
                "planned_layers": 3,
                "buy_price": 11.2,
                "pnl_pct": -20,
            }
        ],
        signals=[{"type": "paper_candidate", "code": "600721", "score": 88}],
    )
    assert "🚀进攻" in text
    assert "依据：晋级率支持；梯队有高度" in text
    assert "池内共1只，💰持股0只，🎯待决1只，👀观察0只" in text
    assert "🎯 百花医药 600721（⏳待决），88分，计划3层" in text
    assert "持仓3层" not in text
    assert "🎯介入" not in text
    assert "leader" not in text


def test_observe_picks_not_labeled_as_actionable() -> None:
    text = format_watch_summary(
        skill_name="龙回头",
        slug="dragon-return",
        trade_date="2026-08-07",
        gate={
            "state": "observe",
            "reasons": ["信号混合"],
            "freshness": {"actual_trade_date": "2026-08-07", "stale": False},
        },
        picks=[
            {
                "code": "600721",
                "name": "百花医药",
                "role": "leader",
                "role_label": "龙头",
                "score": 58,
                "intent": "observe",
                "planned_layers": 0,
            }
        ],
        signals=[
            {
                "type": "theme_interval_weak",
                "code": "theme",
                "name": "高位板",
                "reason": "区间强度高位走弱：主线持续性存疑",
            }
        ],
    )
    assert "🎯介入" not in text
    assert "池内共1只，💰持股0只，🎯待决0只，👀观察1只" in text
    assert "👀 百花医药 600721，58分" in text
    assert "仅观察" not in text
    assert "区间" in text or "走弱" in text


def test_dragon_watch_summary_displays_all_five_observes() -> None:
    picks = [
        {
            "code": f"60072{index}",
            "name": name,
            "role": "leader",
            "role_label": "龙头",
            "score": 70 - index,
            "intent": "observe",
        }
        for index, name in enumerate(["甲", "乙", "丙", "丁", "百花医药"], start=1)
    ]

    text = format_watch_summary(
        skill_name="龙回头",
        slug="dragon-return",
        trade_date="2026-08-11",
        gate={
            "state": "empty",
            "reasons": ["空仓窗口"],
            "freshness": {"actual_trade_date": "2026-08-11", "stale": False},
        },
        picks=picks,
    )

    assert "池内共5只，💰持股0只，🎯待决0只，👀观察5只" in text
    assert "百花医药" in text


def test_buy_candidate_is_pending_not_an_executed_entry() -> None:
    text = format_watch_summary(
        skill_name="龙回头",
        slug="dragon-return",
        trade_date="2026-08-12",
        picks=[
            {
                "code": "603228",
                "name": "景旺电子",
                "bucket": "observe",
                "action": "buy",
                "score": 69,
                "planned_layers": 1,
            },
            {
                "code": "600272",
                "name": "开开实业",
                "bucket": "observe",
                "action": "observe",
                "score": 70,
            },
        ],
    )

    assert "池内共2只，💰持股0只，🎯待决1只，👀观察1只" in text
    assert "🎯 景旺电子 603228（⏳待决），69分，计划1层" in text
    assert "持仓1层" not in text
    assert "🎯介入" not in text
    assert "仅观察" not in text


def test_dragon_watch_summary_renders_one_ordered_unified_pool() -> None:
    text = format_watch_summary(
        skill_name="龙回头",
        slug="dragon-return",
        trade_date="2026-08-11",
        picks=[
            {
                "code": "600001",
                "name": "持仓甲",
                "bucket": "position",
                "action": "holding",
                "score": 81,
                "layers": 2,
                "mark_cost": 10.25,
            },
            {
                "code": "000859",
                "name": "买入乙",
                "bucket": "observe",
                "action": "buy",
                "score": 73,
                "planned_layers": 2,
                "action_reason": "回撤到位",
            },
            {
                "code": "300001",
                "name": "调仓丙",
                "bucket": "position",
                "action": "rebalance",
                "score": 72,
                "layers": 1.5,
                "mark_cost": 20.5,
                "action_reason": "冲高减仓",
            },
            {
                "code": "600002",
                "name": "卖出丁",
                "bucket": "position",
                "action": "sell",
                "score": 65,
                "layers": 1,
                "mark_cost": 8.8,
                "action_reason": "跌破十日线",
            },
            {
                "code": "600003",
                "name": "新进戊",
                "bucket": "observe",
                "action": "observe",
                "score": 61,
            },
            {
                "code": "600004",
                "name": "普通己",
                "bucket": "observe",
                "action": "observe",
                "score": 60,
                "decision_reason": "龙头身份合格；龙空龙空仓；龙回头尚未回撤",
            },
        ],
        observe_changes={
            "added": [
                {
                    "code": "600003",
                    "name": "新进戊",
                    "score": 61,
                    "reason": "首次入选",
                }
            ],
            "dropped": [
                {
                    "code": "600005",
                    "name": "移出庚",
                    "score": 58,
                    "reason": "角色走弱",
                }
            ],
            "changed": True,
        },
    )

    expected_lines = [
        "池内共6只，💰持股3只，🎯待决1只，👀观察2只，🔄调整2只",
        "💰 持仓甲 600001，81分，持仓2层，成本10.25",
        "🎯 买入乙 000859（⏳待决），73分，计划2层，回撤到位",
        "🔄 调仓丙 300001（🔧调仓），72分，持仓1.5层，成本20.5，冲高减仓",
        "🔄 卖出丁 600002（💸卖出），65分，持仓1层，成本8.8，跌破十日线",
        "👀 新进戊 600003（🆕新进），61分，首次入选",
        "👀 普通己 600004，60分",
        "👀 移出庚 600005（🗑️移出），58分，角色走弱",
    ]
    for line in expected_lines:
        assert line in text
    assert [text.index(line) for line in expected_lines] == sorted(
        text.index(line) for line in expected_lines
    )
    assert "🐲" not in text
    assert "龙头身份合格" not in text
    assert "龙空龙空仓" not in text
    assert "龙回头尚未回撤" not in text
    assert "🔄【观察池变更】" not in text


def test_leader_signals_share_second_line() -> None:
    text = format_watch_summary(
        skill_name="市场龙头地图",
        slug="market-leader-map",
        trade_date="2026-08-07",
        gate={
            "state": "empty",
            "reasons": ["晋级率低"],
            "freshness": {"actual_trade_date": "2026-08-07", "stale": False},
        },
        signals=[
            {
                "type": "gate_empty",
                "code": "market",
                "reason": "晋级率低",
            },
            {
                "type": "leader_watch",
                "code": "600001",
                "name": "测试龙",
                "role": "leader",
                "reason": "龙头：题材内连板最高",
            },
        ],
    )
    assert "🛑空仓" in text
    assert "依据：晋级率低" in text
    assert "🐉龙头 测试龙" in text
    assert "market" not in text.lower()


def test_ma10_scrubbed_to_chinese() -> None:
    text = format_watch_summary(
        skill_name="龙回头",
        slug="dragon-return",
        trade_date="2026-08-07",
        gate={
            "state": "empty",
            "reasons": ["跌破 MA10"],
            "freshness": {"actual_trade_date": "2026-08-07", "stale": False},
        },
        signals=[
            {
                "type": "leader_weak",
                "code": "600001",
                "name": "测试龙",
                "role": "weakened",
                "reason": "走弱：跌破 MA10",
            }
        ],
    )
    assert "十日线" in text
    assert "MA10" not in text


def test_dashboard_shows_metrics_themes_and_leaders() -> None:
    text = format_watch_summary(
        skill_name="龙回头",
        slug="dragon-return",
        trade_date="2026-08-07",
        gate={
            "state": "empty",
            "reasons": ["晋级率低", "梯队有高度", "主线强度支持"],
            "freshness": {
                "actual_trade_date": "2026-08-07",
                "snapshot_time": "2026-08-07T06:30:05Z",
                "stale": False,
            },
            "metrics": {
                "promotion_rate": 0.1772,
                "broken_rate": 0.3191,
                "seal_rate": 0.7158,
                "limit_down_rate": 0.0725,
                "breadth": 0.491,
                "temperature": None,
                "height": 4.0,
                "limit_up_count": 64,
                "limit_down_count": 5,
                "main_net_yi": 308.9,
            },
        },
        themes=[
            {
                "theme_name": "医药",
                "strength": 18479,
                "pct_chg": 2.882,
                "main_net_amount": 7420609404.0,
            },
            {
                "theme_name": "通信",
                "strength": 15990,
                "pct_chg": 1.717,
                "main_net_amount": 21047189400.0,
            },
        ],
        leaders=[
            {
                "name": "百花医药",
                "code": "600721",
                "theme_name": "医药",
                "ladder_level": 4,
                "today_pct": -1.87,
                "in_ladder": True,
                "is_limit_up": True,
                "bar_date": "2026-08-07",
            }
        ],
        signals=[
            {
                "type": "leader_watch",
                "code": "600721",
                "name": "百花医药",
                "role": "leader",
            }
        ],
    )
    assert "📊盘面" in text
    assert "晋级17.7%" in text
    assert "封板71.6%" in text
    assert "炸板31.9%" in text
    assert "跌停率7.2%" in text or "跌停率7.3%" in text
    assert "宽度49.1%" in text
    assert "最高4板" in text
    assert "涨停64/跌停5" in text
    assert "主力+" in text and "亿" in text
    assert "🏷最强" in text
    assert "医药" in text and "通信" in text
    assert "+74.2亿" in text or "+74亿" in text
    assert "🐉龙头" in text
    assert "百花医药" in text
    assert "4板" in text
    assert "涨停" in text
    assert "-1.9%" not in text
    # 龙头地图行已展示时，不再重复 🐉龙头 信号行
    assert text.count("🐉") == 1
    assert "温度" not in text  # 缺温度不硬编
    assert "截至14:30" in text


def test_stale_gate_hides_dashboard_that_looks_live() -> None:
    text = format_watch_summary(
        skill_name="龙回头",
        slug="dragon-return",
        trade_date="2026-08-07",
        gate={
            "state": "empty",
            "reasons": ["数据非当日实时，按空仓处理"],
            "freshness": {
                "actual_trade_date": "2026-08-06",
                "stale": True,
                "snapshot_time": "2026-08-06T07:00:00Z",
            },
            "metrics": {"promotion_rate": 0.5, "broken_rate": 0.1, "height": 5},
        },
        themes=[{"theme_name": "昨日题材", "strength": 99, "pct_chg": 9, "main_net_amount": 1e10}],
        leaders=[{"name": "昨日龙", "code": "600001", "today_pct": 9.9}],
    )
    assert "📊盘面" not in text
    assert "🏷最强" not in text
    assert "🐉龙头" not in text
    assert "昨日题材" not in text
    assert "非当日" in text or "非实时" in text
