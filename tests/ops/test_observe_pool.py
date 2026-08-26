"""观察池规则：日更精选、粘性续盯、替换分差、变更汇报、文案一行。"""
from __future__ import annotations

from src.ops.application.skill_watch.observe_pool import (
    format_observe_change_report,
    format_observe_line,
    format_observe_reason,
    merge_observe_pool,
    observe_intraday_alerts,
    select_daily_observes,
)


def test_select_daily_observes_filters_score_and_cap() -> None:
    rows = [
        {"code": "1", "score": 58, "role_label": "龙头"},
        {"code": "2", "score": 54, "role_label": "中军"},
        {"code": "3", "score": 44, "role_label": "龙头"},
        {"code": "4", "score": 32, "role_label": "中军"},
    ]
    picked = select_daily_observes(rows, buy_codes=set(), min_score=50, max_daily=2)
    assert [r["code"] for r in picked] == ["1", "2"]


def test_merge_observe_pool_sticky_keeps_and_reports() -> None:
    prev = [
        {"code": "a", "intent": "observe", "score": 51, "name": "旧A"},
        {"code": "b", "intent": "observe", "score": 55, "name": "旧B"},
        {"code": "c", "intent": "observe", "score": 60, "name": "旧C"},
    ]
    fresh = [
        {"code": "d", "intent": "observe", "score": 70, "name": "新D"},
        {"code": "b", "intent": "observe", "score": 56, "name": "新B"},
    ]
    merged, report = merge_observe_pool(
        held_codes={"c"},
        fresh_observes=fresh,
        previous_items=prev,
        min_score=50,
        max_pool=5,
        max_daily_adds=2,
        replace_margin=8,
    )
    codes = [m["code"] for m in merged]
    assert "c" not in codes  # 已持仓不进观察池
    assert codes[0] == "d"
    assert "b" in codes
    assert "a" in codes  # 粘性保留
    assert len(codes) <= 5
    assert any(r["code"] == "d" for r in report["added"])
    assert any(r["code"] == "c" and r["score"] == 60 for r in report["dropped"])
    assert report["changed"] is True


def test_merge_observe_pool_miss_days_drops_stale() -> None:
    prev = [
        {
            "code": "x",
            "intent": "observe",
            "score": 55,
            "name": "久未扫",
            "observe_since": "2026-08-01",
            "last_seen_date": "2026-08-05",
            "miss_days": 1,
        },
        {
            "code": "y",
            "intent": "observe",
            "score": 58,
            "name": "仍盯",
            "observe_since": "2026-08-01",
            "last_seen_date": "2026-08-06",
            "miss_days": 0,
        },
    ]
    merged, report = merge_observe_pool(
        held_codes=set(),
        fresh_observes=[],
        previous_items=prev,
        min_score=50,
        max_pool=5,
        max_daily_adds=2,
        trade_date="2026-08-07",
        max_miss_days=2,
    )
    codes = [m["code"] for m in merged]
    assert "x" not in codes
    assert "y" in codes
    assert merged[0]["miss_days"] == 1
    assert any(
        r["code"] == "x" and "未命中扫描" in r["reason"] for r in report["dropped"]
    )
    assert report["changed"] is True


def test_merge_observe_pool_refresh_sets_dates() -> None:
    prev = [
        {
            "code": "b",
            "intent": "observe",
            "score": 55,
            "name": "旧B",
            "observe_since": "2026-08-01",
            "last_seen_date": "2026-08-05",
            "miss_days": 1,
        },
    ]
    fresh = [{"code": "b", "intent": "observe", "score": 56, "name": "新B"}]
    merged, _report = merge_observe_pool(
        held_codes=set(),
        fresh_observes=fresh,
        previous_items=prev,
        trade_date="2026-08-07",
        max_miss_days=2,
    )
    row = merged[0]
    assert row["observe_since"] == "2026-08-01"
    assert row["last_seen_date"] == "2026-08-07"
    assert row["miss_days"] == 0


def test_merge_observe_pool_replace_needs_margin() -> None:
    prev = [
        {"code": "w", "intent": "observe", "score": 52, "name": "弱票"},
        {"code": "s", "intent": "observe", "score": 70, "name": "强票"},
    ]
    # 仅 +5 不够换；+10 才够
    weak_fresh = [{"code": "n", "intent": "observe", "score": 57, "name": "略强"}]
    merged_keep, report_keep = merge_observe_pool(
        held_codes=set(),
        fresh_observes=weak_fresh,
        previous_items=prev,
        min_score=50,
        max_pool=2,
        max_daily_adds=1,
        replace_margin=8,
    )
    assert [m["code"] for m in merged_keep] == ["s", "w"]
    assert report_keep["replaced"] == []
    assert report_keep["added"] == []

    strong_fresh = [{"code": "n", "intent": "observe", "score": 62, "name": "明显强"}]
    merged_rep, report_rep = merge_observe_pool(
        held_codes=set(),
        fresh_observes=strong_fresh,
        previous_items=prev,
        min_score=50,
        max_pool=2,
        max_daily_adds=1,
        replace_margin=8,
    )
    assert [m["code"] for m in merged_rep] == ["s", "n"]
    assert len(report_rep["replaced"]) == 1
    assert report_rep["replaced"][0]["out_code"] == "w"
    assert report_rep["replaced"][0]["in_code"] == "n"
    assert report_rep["added"] == []  # 替换不重复算新增


def test_format_observe_change_report_empty_when_unchanged() -> None:
    assert (
        format_observe_change_report(
            {
                "kept": [{"code": "1", "name": "甲"}],
                "added": [],
                "replaced": [],
                "dropped": [],
                "changed": False,
            }
        )
        == ""
    )
    assert format_observe_change_report(None) == ""
    assert format_observe_change_report({"changed": False}) == ""


def test_format_observe_change_report_sections() -> None:
    changed = format_observe_change_report(
        {
            "kept": [{"code": "1", "name": "甲"}],
            "added": [
                {"code": "2", "name": "乙", "reason": "龙头·半导体·58分·新入池"},
            ],
            "replaced": [
                {
                    "out_code": "3",
                    "out_name": "丙",
                    "in_code": "4",
                    "in_name": "丁",
                    "reason": "优胜劣汰",
                }
            ],
            "upgraded": [{"code": "5", "name": "戊", "reason": "原观察池"}],
            "dropped": [],
            "changed": True,
        }
    )
    assert "续盯" in changed and "新进观察 乙" in changed and "替换 丙" in changed
    assert "升级可买 戊 5" in changed


def test_format_observe_line_compact() -> None:
    from src.ops.application.skill_watch.observe_pool import role_badge

    assert role_badge("中军") == "🛡️"
    assert role_badge(None, "secondary") == "🛡️"
    line = format_observe_line(
        {"name": "百花医药", "code": "600721", "score": 58, "role_label": "龙头"},
        index=1,
    )
    assert line == "1、👀 百花医药 600721，58分，🐲，仅观察"
    mid = format_observe_line(
        {"name": "人民同泰", "code": "600829", "score": 54, "role_label": "中军"},
        index=2,
    )
    assert mid == "2、👀 人民同泰 600829，54分，🛡️，仅观察"


def test_observe_intraday_alerts_role_weak() -> None:
    lines = observe_intraday_alerts(
        [{"code": "600721", "name": "百花医药", "intent": "observe", "role_label": "走弱"}],
        {},
    )
    assert lines == ["⚠️观察预警 百花医药 600721 · 走弱"]


def test_observe_intraday_alerts_score_below_min() -> None:
    lines = observe_intraday_alerts(
        [{"code": "600829", "name": "人民同泰", "intent": "observe", "score": 44}],
        {},
        min_score=50,
    )
    assert lines == ["⚠️观察预警 人民同泰 600829 · 跌破分线"]


def test_observe_intraday_alerts_drop_pct() -> None:
    lines = observe_intraday_alerts(
        [
            {
                "code": "000001",
                "name": "平安",
                "intent": "observe",
                "score": 55,
                "ref_close": 10.0,
            }
        ],
        {"000001": {"last": 9.38}},
        drop_pct=-5.0,
    )
    assert lines == ["⚠️观察预警 平安 000001 · -6.2%"]


def test_observe_intraday_alerts_healthy_none() -> None:
    lines = observe_intraday_alerts(
        [
            {
                "code": "600519",
                "name": "茅台",
                "intent": "observe",
                "score": 58,
                "role_label": "龙头",
                "ref_close": 100.0,
            }
        ],
        {"600519": {"last": 102.0}},
    )
    assert lines == []


def test_format_observe_reason_binds_role_theme_score() -> None:
    row = {"role_label": "龙头", "theme_name": "半导体", "score": 58}
    assert format_observe_reason(row, why="未达可买线") == "龙头·半导体·58分·未达可买线"
    bare = {"role_label": "中军", "score": 52}
    assert format_observe_reason(bare, why="非进攻窗") == "中军·52分·非进攻窗"


def test_format_observe_line_shows_unified_suite_decision() -> None:
    line = format_observe_line(
        {
            "code": "600721",
            "name": "百花医药",
            "score": 73,
            "role": "leader",
            "decision_reason": "龙头身份合格；龙空龙空仓；龙回头尚未回撤",
        }
    )
    assert "百花医药 600721" in line
    assert "龙头身份合格；龙空龙空仓；龙回头尚未回撤" in line


def test_merge_add_reason_carries_theme_to_report() -> None:
    fresh = [
        {
            "code": "x",
            "intent": "observe",
            "score": 62,
            "name": "新票",
            "role_label": "龙头",
            "theme_name": "AI算力",
        }
    ]
    _, report = merge_observe_pool(
        held_codes=set(),
        fresh_observes=fresh,
        previous_items=[],
        min_score=50,
        max_pool=5,
        max_daily_adds=2,
    )
    assert report["added"][0]["reason"] == "龙头·AI算力·62分·新入池"
    changed = format_observe_change_report(report)
    assert "AI算力" in changed
