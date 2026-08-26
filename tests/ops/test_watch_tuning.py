"""战法监测：调参启停、竞价确认、角色留痕。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.ops.application.skill_watch.auction_confirm import (
    evaluate_auction,
    in_auction_window,
)
from src.ops.application.skill_watch.leader_map import apply_auction_stances
from src.ops.application.skill_watch.tuning import (
    apply_preset,
    default_tuning,
    list_presets,
    load_tuning,
    normalize_tuning,
    preset_tuning,
    reset_tuning,
    save_tuning,
    stage_enabled,
    tuning_schema,
)
from src.ops.infrastructure.store import OpsStore

_TZ = ZoneInfo("Asia/Shanghai")


def test_tuning_drops_unknown_keys_and_clamps_out_of_range() -> None:
    tuning = normalize_tuning(
        {
            "stages": {"market_gate": False, "不存在的段": True},
            "gate": {"promotion_attack": 99, "野字段": 1},
            "scan": {"max_candidates": -5, "theme_limit": 2.7},
        }
    )

    assert tuning["stages"]["market_gate"] is False
    assert "不存在的段" not in tuning["stages"]
    assert tuning["gate"]["promotion_attack"] == 1.0
    assert "野字段" not in tuning["gate"]
    assert tuning["scan"]["max_candidates"] == 0
    assert tuning["scan"]["theme_limit"] == 2


def test_tuning_saves_per_section_without_resetting_the_others(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        save_tuning(store, "demo", {"scan": {"candidate_score": 80}})
        save_tuning(store, "demo", {"stages": {"auction_confirm": False}})
        saved = load_tuning(store, "demo")

        assert saved["scan"]["candidate_score"] == 80
        assert saved["stages"]["auction_confirm"] is False
        assert saved["stages"]["market_gate"] is True

        assert reset_tuning(store, "demo") == default_tuning()
        assert load_tuning(store, "demo") == default_tuning()


def test_unsaved_slug_falls_back_to_defaults(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        assert load_tuning(store, "never-configured") == default_tuning()
    assert stage_enabled(None, "market_gate") is True


def test_tuning_schema_includes_named_presets() -> None:
    schema = tuning_schema()
    ids = {item["id"] for item in schema["presets"]}
    assert ids == {"aggressive", "balanced", "defensive"}
    assert list_presets()[1]["label"] == "中性"


def test_preset_tuning_offsets_from_defaults() -> None:
    base = default_tuning()
    aggressive = preset_tuning("aggressive")
    defensive = preset_tuning("defensive")

    assert aggressive["scan"]["candidate_score"] < base["scan"]["candidate_score"]
    assert aggressive["scan"]["max_candidates"] > base["scan"]["max_candidates"]
    assert aggressive["auction"]["abandon_gap_pct"] < base["auction"]["abandon_gap_pct"]

    assert defensive["scan"]["candidate_score"] > base["scan"]["candidate_score"]
    assert defensive["scan"]["max_candidates"] < base["scan"]["max_candidates"]
    assert defensive["auction"]["abandon_gap_pct"] > base["auction"]["abandon_gap_pct"]

    assert preset_tuning("balanced") == default_tuning()


def test_apply_preset_persists_and_keeps_stage_switches(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        save_tuning(store, "demo", {"stages": {"market_gate": False}})
        applied = apply_preset(store, "demo", "defensive")

        assert applied["stages"]["market_gate"] is False
        assert applied["scan"]["max_candidates"] == 1
        assert load_tuning(store, "demo")["scan"]["max_candidates"] == 1


def test_unknown_preset_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="未知预设"):
        preset_tuning("ultra")


def test_auction_window_only_covers_the_open() -> None:
    assert in_auction_window(datetime(2026, 8, 7, 9, 20, tzinfo=_TZ)) is True
    assert in_auction_window(datetime(2026, 8, 7, 10, 30, tzinfo=_TZ)) is False
    # 周六没有竞价
    assert in_auction_window(datetime(2026, 8, 8, 9, 20, tzinfo=_TZ)) is False


def test_auction_downgrades_and_abandons_by_gap() -> None:
    leaders = [
        {"code": "600001", "name": "强龙", "role": "leader"},
        {"code": "600002", "name": "弱龙", "role": "leader"},
        {"code": "600003", "name": "砸盘龙", "role": "leader"},
        {"code": "600004", "name": "缺数龙", "role": "leader"},
    ]
    snapshot = {
        "structured": {
            "rows": [
                {"code": "600001", "pctChg": 5.0, "limitBuyAmount": 1000},
                {"code": "600002", "pctChg": -3.0},
                {"code": "600003", "pctChg": -8.0},
            ]
        }
    }

    stances = {row["code"]: row for row in evaluate_auction(leaders, snapshot)}

    assert stances["600001"]["stance"] == "confirmed"
    assert stances["600002"]["stance"] == "downgraded"
    assert stances["600003"]["stance"] == "abandoned"
    assert stances["600004"]["stance"] == "pending"


def test_auction_not_ready_never_pretends_to_confirm() -> None:
    stances = evaluate_auction(
        [{"code": "600001", "role": "leader"}],
        {"structured": {"qualityWarnings": ["AUCTION_DATA_NOT_READY"], "rows": []}},
    )

    assert stances[0]["stance"] == "pending"


def test_auction_abandon_rewrites_the_role_so_downstream_stops_buying() -> None:
    entries = [
        {"code": "600001", "role": "leader", "role_label": "龙头", "role_basis": "连板最高"},
        {"code": "600002", "role": "leader", "role_label": "龙头", "role_basis": "涨幅最高"},
    ]

    apply_auction_stances(
        entries,
        [
            {"code": "600001", "stance": "abandoned", "gap_pct": -8.0, "reason": "竞价砸盘"},
            {"code": "600002", "stance": "downgraded", "gap_pct": -3.0, "reason": "承接转弱"},
        ],
    )

    assert entries[0]["role"] == "failed"
    assert entries[1]["role"] == "secondary"
    assert entries[0]["auction_stance"] == "abandoned"


def test_leader_role_history_is_append_only_and_yields_transitions(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        store.record_leader_roles(
            "demo",
            trade_date="2026-08-07",
            observed_at="2026-08-07T09:35:00+08:00",
            gate_state="dragon",
            entries=[{"code": "600001", "name": "测试龙", "role": "leader", "gain_20_pct": 30}],
        )
        store.record_leader_roles(
            "demo",
            trade_date="2026-08-07",
            observed_at="2026-08-07T14:00:00+08:00",
            gate_state="observe",
            entries=[
                {
                    "code": "600001",
                    "name": "测试龙",
                    "role": "weakened",
                    "role_basis": "失守 MA10",
                    "gain_20_pct": 12,
                }
            ],
        )

        from src.ops.application.skill_watch.role_stats import role_transitions

        history = store.list_leader_roles("demo")
        transitions = role_transitions(history)

        # 同一天同一只票的两次观测都保留，不像缓存那样被覆盖
        assert len(history) == 2
        assert transitions[0]["from_role"] == "leader"
        assert transitions[0]["to_role"] == "weakened"
        assert transitions[0]["basis"] == "失守 MA10"

        assert store.prune_leader_roles(before_date="2026-08-08") == 2
        assert store.list_leader_roles("demo") == []
