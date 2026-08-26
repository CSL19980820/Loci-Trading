"""观察池盘中预警闭环与日终角色回填。"""
from __future__ import annotations

from pathlib import Path

from src.ops.application.jobs import paper_quant_eod
from src.ops.application.skill_watch import observe_lifecycle
from src.ops.infrastructure.store import OpsStore


def test_observe_alert_state_is_slug_scoped_and_expires(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        alerts, lines = observe_lifecycle.collect_observe_alerts(
            [
                {
                    "code": "000001",
                    "name": "平安",
                    "intent": "observe",
                    "score": 58,
                    "ref_close": 10.0,
                }
            ],
            {"000001": {"last": 9.38}},
            trade_date="2026-08-07",
            drop_pct=-5.0,
        )
        assert lines == ["⚠️观察预警 平安 000001 · -6.2%"]
        assert alerts == [
            {
                "code": "000001",
                "name": "平安",
                "reason": "-6.2%",
                "trade_date": "2026-08-07",
                "kind": "drop_pct",
                "alert_kind": "drop_pct",
            }
        ]

        observe_lifecycle.save_observe_alerts(
            store,
            slug="dragon-return",
            trade_date="2026-08-07",
            alerts=alerts,
        )
        assert observe_lifecycle.load_observe_alerts(
            store, slug="dragon-return", trade_date="2026-08-07"
        ) == alerts
        assert (
            observe_lifecycle.load_observe_alerts(
                store, slug="other-watch", trade_date="2026-08-07"
            )
            == []
        )
        assert (
            observe_lifecycle.load_observe_alerts(
                store, slug="dragon-return", trade_date="2026-08-10"
            )
            == []
        )
        assert store.get_setting(observe_lifecycle.alert_setting_key("dragon-return")) is None


def test_eod_severe_observe_alert_drops_currently_invalid_item(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin("dragon-return")
        store.upsert_nextday_plan(
            {
                "slug": "dragon-return",
                "plan_date": "2026-08-07",
                "body_text": "",
                "items": [
                    {
                        "code": "600001",
                        "name": "破位龙",
                        "intent": "observe",
                        "role": "failed",
                        "role_label": "结构破坏",
                        "score": 58,
                    }
                ],
                "source": "test",
            }
        )
        observe_lifecycle.save_observe_alerts(
            store,
            slug="dragon-return",
            trade_date="2026-08-07",
            alerts=[
                {
                    "code": "600001",
                    "name": "破位龙",
                    "reason": "结构破坏",
                    "trade_date": "2026-08-07",
                    "kind": "structure_failed",
                }
            ],
        )

        picks, changes = paper_quant_eod._nextday_picks_after_eod(
            store,
            slug="dragon-return",
            trade_date="2026-08-07",
            positions=[],
        )

    assert not any(item["code"] == "600001" for item in picks)
    dropped = next(row for row in changes["dropped"] if row["code"] == "600001")
    assert "预警复核" in dropped["reason"]


def test_eod_drop_alert_keeps_qualified_item_for_follow_up(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin("dragon-return")
        store.upsert_nextday_plan(
            {
                "slug": "dragon-return",
                "plan_date": "2026-08-07",
                "body_text": "",
                "items": [
                    {
                        "code": "600002",
                        "name": "回踩龙",
                        "intent": "observe",
                        "role": "leader",
                        "role_label": "龙头",
                        "score": 58,
                    }
                ],
                "source": "test",
            }
        )
        observe_lifecycle.save_observe_alerts(
            store,
            slug="dragon-return",
            trade_date="2026-08-07",
            alerts=[
                {
                    "code": "600002",
                    "name": "回踩龙",
                    "reason": "-6.0%",
                    "trade_date": "2026-08-07",
                    "kind": "drop_pct",
                }
            ],
        )

        picks, changes = paper_quant_eod._nextday_picks_after_eod(
            store,
            slug="dragon-return",
            trade_date="2026-08-07",
            positions=[],
        )

    assert [item["code"] for item in picks] == ["600002"]
    assert changes["dropped"] == []
    assert changes["alert_follow_up"][0]["code"] == "600002"
    assert changes["alert_follow_up"][0]["reason"] == "-6.0%"


def test_eod_role_backfill_refreshes_old_observe_item(tmp_path: Path, monkeypatch) -> None:
    def fake_scan(*_args, **_kwargs):
        return {
            "picks": [],
            "entries": [
                {
                    "code": "600003",
                    "name": "回填龙",
                    "role": "secondary",
                    "role_label": "中军",
                    "theme_code": "T1",
                    "theme_name": "AI主线",
                }
            ],
            "ranked": [
                {
                    "code": "600003",
                    "name": "回填龙",
                    "role": "secondary",
                    "role_label": "中军",
                    "theme_code": "T1",
                    "theme_name": "AI主线",
                    "score": 72,
                }
            ],
        }

    import src.ops.application.skill_watch as skill_watch

    monkeypatch.setattr(skill_watch, "run_skill_watch", fake_scan)
    with OpsStore(tmp_path / "good.db") as store:
        store.ensure_paper_cabin("dragon-return")
        store.upsert_nextday_plan(
            {
                "slug": "dragon-return",
                "plan_date": "2026-08-07",
                "body_text": "",
                "items": [
                    {
                        "code": "600003",
                        "name": "旧名",
                        "intent": "observe",
                        "role": "leader",
                        "role_label": "龙头",
                        "score": 55,
                    }
                ],
                "source": "test",
            }
        )
        picks, changes = paper_quant_eod._nextday_picks_after_eod(
            store,
            slug="dragon-return",
            trade_date="2026-08-07",
            positions=[],
        )

    refreshed = next(item for item in picks if item["code"] == "600003")
    assert refreshed["name"] == "回填龙"
    assert refreshed["role_label"] == "中军"
    assert refreshed["theme_name"] == "AI主线"
    assert refreshed["score"] == 72
    assert changes["dropped"] == []


def test_eod_role_backfill_removes_weakened_item_without_miss_days(
    tmp_path: Path, monkeypatch
) -> None:
    def fake_scan(*_args, **_kwargs):
        return {
            "picks": [],
            "entries": [
                {
                    "code": "600004",
                    "name": "走弱龙",
                    "role": "weakened",
                    "role_label": "走弱",
                    "theme_name": "旧主线",
                }
            ],
            "ranked": [],
        }

    import src.ops.application.skill_watch as skill_watch

    monkeypatch.setattr(skill_watch, "run_skill_watch", fake_scan)
    with OpsStore(tmp_path / "weak.db") as store:
        store.ensure_paper_cabin("dragon-return")
        store.upsert_nextday_plan(
            {
                "slug": "dragon-return",
                "plan_date": "2026-08-07",
                "body_text": "",
                "items": [
                    {
                        "code": "600004",
                        "name": "旧走弱龙",
                        "intent": "observe",
                        "role": "leader",
                        "role_label": "龙头",
                        "score": 58,
                    }
                ],
                "source": "test",
            }
        )
        picks, changes = paper_quant_eod._nextday_picks_after_eod(
            store,
            slug="dragon-return",
            trade_date="2026-08-07",
            positions=[],
        )

    assert not any(item["code"] == "600004" for item in picks)
    assert any(row["code"] == "600004" for row in changes["dropped"])
