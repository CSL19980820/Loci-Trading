"""开盘啦区间强度软过滤单测。"""
from __future__ import annotations

from src.ops.application.skill_watch.theme_interval import (
    apply_theme_interval,
    index_concept_board,
    parse_sector_quadrants,
)


def _live_sector_payload() -> dict:
    """贴近实测：四象限出自细分概念池，与盘中大类板名字零交集。"""
    return {
        "structured": {
            "topLists": {
                "continuingStrong": [
                    {"name": "HBM存储", "recentChange": 22.8, "periodChange": 40.2},
                    {"name": "光刻机概念", "recentChange": 22.7, "periodChange": 13.8},
                ],
                "emerging": [{"name": "超聚变", "recentChange": 23.0, "periodChange": -4.0}],
                "weakening": [{"name": "车路云一体化", "recentChange": -0.2}],
                "weak": [],
            }
        }
    }


def _live_concept_payload() -> dict:
    return {
        "structured": {
            "rows": [
                {"themeCode": "concept:74", "themeName": "HBM存储", "pctChg": 1.19, "mainNetAmount": 856251230},
                {"themeCode": "concept:80", "themeName": "光刻机概念", "pctChg": 0.73, "mainNetAmount": 412000000},
                {"themeCode": "concept:91", "themeName": "超聚变", "pctChg": 0.09, "mainNetAmount": 120000000},
            ]
        }
    }


def _live_featured_themes() -> list[dict]:
    return [
        {"theme_code": "801250k", "theme_name": "并购重组", "strength": 4597, "main_net_amount": 4.73e8},
        {"theme_code": "801045k", "theme_name": "医药", "strength": 4545, "main_net_amount": 7.18e8},
        {"theme_code": "801001k", "theme_name": "芯片", "strength": 3948, "main_net_amount": 48.6e8},
    ]


def _sector_payload() -> dict:
    return {
        "structuredContent": {
            "topLists": {
                "continuingStrong": [
                    {"name": "芯片", "recentChange": 18.0, "periodChange": 10.0, "todayChange": 3.0}
                ],
                "emerging": [
                    {"name": "短线热点", "recentChange": 22.0, "periodChange": -5.0, "todayChange": 5.0}
                ],
                "weakening": [
                    {"name": "高位板", "recentChange": -4.0, "periodChange": 12.0, "todayChange": 0.5}
                ],
                "weak": [],
            }
        }
    }


def test_parse_sector_quadrants_maps_names() -> None:
    parsed = parse_sector_quadrants(_sector_payload())
    assert parsed["芯片"]["interval_quadrant"] == "continuingStrong"
    assert parsed["短线热点"]["interval_label"] == "低位启动"
    assert parsed["高位板"]["interval_quadrant"] == "weakening"


def test_apply_theme_interval_prefers_continuing_over_one_day_spike() -> None:
    themes = [
        {"theme_code": "a", "theme_name": "短线热点", "strength": 9000, "main_net_amount": 1e8},
        {"theme_code": "b", "theme_name": "芯片", "strength": 8000, "main_net_amount": 5e7},
        {"theme_code": "c", "theme_name": "高位板", "strength": 8500, "main_net_amount": 2e7},
    ]
    selected, warnings, meta = apply_theme_interval(themes, _sector_payload(), keep=2)
    assert [row["theme_name"] for row in selected] == ["芯片", "短线热点"]
    assert selected[0]["interval_label"] == "持续强势"
    assert meta["status"] == "ok"
    assert meta["matched"] == 3
    assert warnings == []


def test_apply_theme_interval_emits_weak_warning_when_selected() -> None:
    themes = [
        {"theme_code": "c", "theme_name": "高位板", "strength": 9500, "main_net_amount": 1e8},
        {"theme_code": "b", "theme_name": "芯片", "strength": 1000, "main_net_amount": 1e7},
    ]
    selected, warnings, meta = apply_theme_interval(themes, _sector_payload(), keep=1)
    assert selected[0]["theme_name"] == "高位板"
    assert meta["status"] == "ok"
    assert any(w["type"] == "theme_interval_weak" for w in warnings)


def test_apply_theme_interval_marks_unavailable_without_sector() -> None:
    themes = [
        {"theme_name": "甲", "strength": 10},
        {"theme_name": "乙", "strength": 20},
    ]
    selected, warnings, meta = apply_theme_interval(themes, None, keep=1)
    assert selected[0]["theme_name"] == "甲"
    assert meta["status"] == "unavailable"
    assert warnings and warnings[0]["type"] == "theme_interval_degraded"


def test_apply_theme_interval_marks_unmatched_names() -> None:
    themes = [
        {"theme_name": "完全没听说过的板", "strength": 99},
        {"theme_name": "另一个陌生板", "strength": 88},
    ]
    selected, warnings, meta = apply_theme_interval(themes, _sector_payload(), keep=2)
    assert meta["status"] == "unmatched"
    assert meta["matched"] == 0
    assert [row["theme_name"] for row in selected] == ["完全没听说过的板", "另一个陌生板"]
    assert any(w["type"] == "theme_interval_degraded" for w in warnings)


def test_index_concept_board_reads_names_and_flows() -> None:
    rows = index_concept_board(_live_concept_payload())
    assert rows["hbm存储"]["main_net_amount"] == 856251230
    assert rows["光刻机概念"]["pct_chg"] == 0.73


def test_interval_slot_injects_subdivided_theme_into_main_pool() -> None:
    """两池名字零交集时，细分主线必须靠名额进池，而不是报「对照未对齐」。"""
    selected, warnings, meta = apply_theme_interval(
        _live_featured_themes(),
        _live_sector_payload(),
        keep=3,
        concept_payload=_live_concept_payload(),
        interval_slots=1,
    )
    assert [row["theme_name"] for row in selected] == ["并购重组", "医药", "HBM存储"]
    assert meta["matched"] == 0
    assert meta["injected"] == 1
    assert meta["status"] == "ok"
    # 名字对不上是两池的常态，不该再往推送里塞降级噪声
    assert warnings == []
    injected = selected[-1]
    assert injected["interval_quadrant"] == "continuingStrong"
    assert injected["theme_source"] == "interval"
    # concept:74 这类代码 theme_stocks 不认，必须留空走 themeName 下钻
    assert injected["theme_code"] == ""
    assert injected["main_net_amount"] == 856251230


def test_interval_slot_survives_concept_row_gap() -> None:
    """细分池按主力净额截断，榜上题材缺行时仍占名额，只是没有盘中数值。"""
    concept = {"structured": {"rows": [{"themeName": "无关板", "pctChg": 1.0, "mainNetAmount": 1e8}]}}
    selected, warnings, meta = apply_theme_interval(
        _live_featured_themes(),
        _live_sector_payload(),
        keep=3,
        concept_payload=concept,
        interval_slots=1,
    )
    assert [row["theme_name"] for row in selected] == ["并购重组", "医药", "HBM存储"]
    assert selected[-1]["main_net_amount"] is None
    assert meta["injected"] == 1
    assert warnings == []


def test_interval_slots_never_take_every_seat() -> None:
    selected, _warnings, meta = apply_theme_interval(
        _live_featured_themes(),
        _live_sector_payload(),
        keep=2,
        concept_payload=_live_concept_payload(),
        interval_slots=5,
    )
    assert [row["theme_name"] for row in selected] == ["并购重组", "HBM存储"]
    assert meta["injected"] == 1


def test_interval_slot_reports_when_concept_board_missing() -> None:
    selected, warnings, meta = apply_theme_interval(
        _live_featured_themes(),
        _live_sector_payload(),
        keep=3,
        concept_payload=None,
        interval_slots=1,
    )
    assert [row["theme_name"] for row in selected] == ["并购重组", "医药", "芯片"]
    assert meta["concept_status"] == "unavailable"
    assert meta["injected"] == 0
    assert [w["role"] for w in warnings] == ["concept_unavailable"]


def test_interval_slot_reuses_pool_row_when_theme_already_ranked() -> None:
    """题材本就在盘中池里时复用原行，别用缺 strength 的细分行顶替它。"""
    themes = [
        *_live_featured_themes()[:2],
        {"theme_code": "801x", "theme_name": "HBM存储", "strength": 3000, "main_net_amount": 1e8},
    ]
    selected, _warnings, meta = apply_theme_interval(
        themes,
        _live_sector_payload(),
        keep=3,
        concept_payload=_live_concept_payload(),
        interval_slots=1,
    )
    names = [row["theme_name"] for row in selected]
    assert names == ["并购重组", "医药", "HBM存储"]
    assert names.count("HBM存储") == 1
    assert meta["injected"] == 1
    kept = selected[-1]
    assert kept["theme_code"] == "801x"
    assert kept["strength"] == 3000
