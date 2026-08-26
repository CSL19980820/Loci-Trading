"""龙王统一监察池：持仓、候选和动作共享同一事实源。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ops.api.paper_quant import build_paper_quant_router
from src.ops.application.jobs.paper_quant_support import (
    _today,
    load_live_pool,
    save_live_pool,
)
from src.ops.application.skill_watch.watch_summary import format_watch_summary
from src.ops.application.unified_monitor_pool import (
    DRAGON_INITIAL_CAPITAL,
    DRAGON_MAX_LAYERS,
    DRAGON_MAX_OBSERVE,
    DRAGON_MAX_POSITIONS,
    get_unified_monitor_pool,
    replace_candidate_feed,
    reconcile_unified_monitor_pool,
)
from src.ops.infrastructure.store import OpsStore


def test_unified_pool_keeps_three_positions_and_five_watch_items(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        cabin = store.ensure_paper_cabin("dragon-return")
        for code in ("600001", "300001", "600002"):
            store.upsert_paper_position(
                cabin["id"],
                code=code,
                name=code,
                layers=1.0,
                mark_cost=10.0,
            )

        snapshot = reconcile_unified_monitor_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
            candidates=[
                {"code": "300001", "name": "创业持仓", "intent": "buy", "score": 99},
                *[
                    {
                        "code": f"30010{i}",
                        "name": f"候选{i}",
                        "intent": "observe",
                        "score": 80 - i,
                    }
                    for i in range(7)
                ],
            ],
            source="test",
        )

        assert snapshot["limits"] == {
            "initial_capital": DRAGON_INITIAL_CAPITAL,
            "max_layers": DRAGON_MAX_LAYERS,
            "max_positions": DRAGON_MAX_POSITIONS,
            "max_observe": DRAGON_MAX_OBSERVE,
            "max_total": 8,
        }
        assert snapshot["counts"] == {"positions": 3, "observe": 5, "total": 8}
        assert len({row["code"] for row in snapshot["items"]}) == 8
        held = [row for row in snapshot["items"] if row["bucket"] == "position"]
        watched = [row for row in snapshot["items"] if row["bucket"] == "observe"]
        assert {row["code"] for row in held} == {"600001", "300001", "600002"}
        assert all(row["action"] == "holding" for row in held)
        assert len(watched) == 5


def test_unified_pool_projects_sell_and_rebalance_without_duplicate_rows(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        cabin = store.ensure_paper_cabin("dragon-return")
        store.upsert_paper_position(
            cabin["id"],
            code="600001",
            name="主板持仓",
            layers=2.0,
            mark_cost=10.0,
        )
        store.upsert_paper_position(
            cabin["id"],
            code="300001",
            name="创业持仓",
            layers=1.0,
            mark_cost=20.0,
        )

        snapshot = reconcile_unified_monitor_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
            candidates=[{"code": "600001", "name": "重复候选", "intent": "observe"}],
            actions=[
                {"code": "600001", "action": "reduce", "reason": "减仓"},
                {"code": "300001", "action": "buy_dip", "reason": "低吸调仓"},
            ],
            source="test",
        )

        by_code = {row["code"]: row for row in snapshot["items"]}
        assert len(snapshot["items"]) == 2
        assert by_code["600001"]["action"] == "sell"
        assert by_code["300001"]["action"] == "rebalance"
        assert all(row["bucket"] == "position" for row in snapshot["items"])


def test_unified_pool_round_trip_is_the_same_snapshot(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin("dragon-return")
        reconcile_unified_monitor_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
            candidates=[{"code": "600721", "name": "百花医药", "intent": "observe"}],
            source="test",
        )
        snapshot = get_unified_monitor_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
        )

        assert [row["code"] for row in snapshot["items"]] == ["600721"]
        assert snapshot["items"][0]["action"] == "observe"


def test_live_pool_projection_overwrites_clears_and_isolates_trade_dates(
    tmp_path: Path,
) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin("dragon-return")
        save_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
            picks=[{"code": "600829", "name": "人民同泰", "intent": "observe"}],
        )
        save_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
            picks=[{"code": "600127", "name": "金健米业", "intent": "observe"}],
        )
        saved = load_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
        )
        assert [row["code"] for row in saved or []] == ["600127"]

        save_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
            picks=[],
        )
        assert (
            load_live_pool(store, slug="dragon-return", trade_date="2026-08-10")
            == []
        )
        assert (
            load_live_pool(store, slug="dragon-return", trade_date="2026-08-11")
            is None
        )


def test_candidate_feeds_replace_independently(tmp_path: Path) -> None:
    """一个扫描器的空结果不能抹掉另一个扫描器刚写入的候选，反向亦然。"""
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin("dragon-return")
        replace_candidate_feed(
            store,
            slug="dragon-return",
            trade_date="2026-08-11",
            feed="skill_watch:dragon-return",
            candidates=[{"code": "600001", "intent": "observe"}],
        )
        replace_candidate_feed(
            store,
            slug="dragon-return",
            trade_date="2026-08-11",
            feed="skill_watch:other-scanner",
            candidates=[{"code": "600002", "intent": "buy"}],
        )
        both = get_unified_monitor_pool(
            store, slug="dragon-return", trade_date="2026-08-11"
        )
        assert {row["code"] for row in both["items"]} == {"600001", "600002"}

        replace_candidate_feed(
            store,
            slug="dragon-return",
            trade_date="2026-08-11",
            feed="skill_watch:dragon-return",
            candidates=[],
        )
        pool_only = get_unified_monitor_pool(
            store, slug="dragon-return", trade_date="2026-08-11"
        )
        assert [row["code"] for row in pool_only["items"]] == ["600002"]
        assert pool_only["items"][0]["candidate_feed"] == "skill_watch:other-scanner"


def test_unified_pool_round_trip_preserves_position_score(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        cabin = store.ensure_paper_cabin("dragon-return")
        store.upsert_paper_position(
            cabin["id"],
            code="600721",
            name="百花医药",
            layers=2.0,
            mark_cost=10.0,
        )
        reconcile_unified_monitor_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
            candidates=[
                {
                    "code": "600721",
                    "name": "百花医药",
                    "intent": "buy",
                    "score": 69,
                }
            ],
            source="test",
        )

        snapshot = get_unified_monitor_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
        )

    assert snapshot["items"][0]["bucket"] == "position"
    assert snapshot["items"][0]["score"] == 69


def test_home_api_and_wecom_summary_consume_the_same_pool(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    trade_date = _today()
    with OpsStore(db) as store:
        store.ensure_paper_cabin("dragon-return")
        snapshot = reconcile_unified_monitor_pool(
            store,
            slug="dragon-return",
            trade_date=trade_date,
            candidates=[
                {
                    "code": "600721",
                    "name": "百花医药",
                    "intent": "observe",
                    "score": 69,
                    "role_label": "龙头",
                }
            ],
            source="skill_watch",
        )
        wecom = format_watch_summary(
            skill_name="龙回头",
            slug="dragon-return",
            trade_date=trade_date,
            picks=snapshot["items"],
        )

    app = FastAPI()
    app.include_router(
        build_paper_quant_router(write_dependency=lambda: None, ops_db=str(db))
    )
    with TestClient(app) as client:
        detail = client.get("/api/ops/paper-cabins/dragon-return").json()
        pool = client.get("/api/ops/paper-cabins/dragon-return/unified-pool").json()

    assert [row["code"] for row in detail["unified_pool"]["items"]] == ["600721"]
    assert [row["code"] for row in pool["items"]] == ["600721"]
    assert "百花医药" in wecom


def test_dragon_return_merge_failure_preserves_complete_unified_pool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.ops.application.jobs.paper_quant_support import load_live_pool, save_live_pool
    from src.ops.application.skill_watch.runner import run_skill_watch

    skill = {
        "slug": "dragon-return",
        "name": "龙回头",
        "enabled": True,
        "metadata": {"strategy_skill": True, "signal_engine": "dragon_return"},
    }
    monkeypatch.setattr(
        "src.ops.application.skills.resolve_skill",
        lambda slug: skill if slug == "dragon-return" else None,
    )
    monkeypatch.setattr(
        "src.ops.application.skill_watch.runner._load_scanner",
        lambda _engine: (
            lambda _call_tool, **_kwargs: {
                "trade_date": "2026-08-11",
                "signals": [],
                "picks": [
                    {
                        "code": "000859",
                        "name": "国风新材",
                        "intent": "observe",
                        "score": 73,
                        "role": "leader",
                    },
                    {
                        "code": "600664",
                        "name": "哈药股份",
                        "intent": "observe",
                        "score": 61,
                        "role": "leader",
                    },
                ],
                "entries": [],
                "leader_map": {"leaders": [], "weakened": []},
                "market_gate": {
                    "state": "empty",
                    "entry_allowed": False,
                    "data_status": "ok",
                    "reason": "空仓窗口",
                },
            }
        ),
    )
    monkeypatch.setattr(
        "src.ops.application.skill_watch.runner._merge_live_observes",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("merge boom")),
    )

    previous = [
        {"code": "000859", "name": "国风新材", "intent": "observe", "score": 73},
        {"code": "000603", "name": "盛达资源", "intent": "observe", "score": 63},
        {"code": "600664", "name": "哈药股份", "intent": "observe", "score": 61},
        {"code": "600721", "name": "百花医药", "intent": "observe", "score": 61},
    ]
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin("dragon-return")
        save_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-11",
            picks=previous,
        )
        result = run_skill_watch(
            {"skill": "dragon-return"},
            call_tool=lambda *_: {},
            store=store,
        )
        saved = load_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-11",
        )

    assert [row["code"] for row in saved or []] == [row["code"] for row in previous]
    assert [row["code"] for row in result["picks"]] == [row["code"] for row in previous]
    assert "统一监察池合并失败，已保留上一快照" in result["warnings"]


def test_dragon_eod_consumes_unified_pool_without_rewriting_it(tmp_path: Path) -> None:
    from src.ops.application.jobs.paper_quant_eod import _nextday_picks_after_eod
    from src.ops.application.jobs.paper_quant_support import save_live_pool

    previous = [
        {"code": "000859", "name": "国风新材", "intent": "observe", "score": 73},
        {"code": "000603", "name": "盛达资源", "intent": "observe", "score": 63},
        {"code": "600664", "name": "哈药股份", "intent": "observe", "score": 61},
        {"code": "600721", "name": "百花医药", "intent": "observe", "score": 61},
    ]
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin("dragon-return")
        save_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-11",
            picks=previous,
        )
        before = store.get_setting("unified_monitor_pool:dragon-return", None)
        picks, _changes = _nextday_picks_after_eod(
            store,
            slug="dragon-return",
            trade_date="2026-08-11",
            positions=[],
        )
        after = store.get_setting("unified_monitor_pool:dragon-return", None)

    assert [row["code"] for row in picks] == [row["code"] for row in previous]
    assert after == before


def test_paper_eod_plan_does_not_advance_unified_pool_trade_date(tmp_path: Path) -> None:
    from src.ops.application.jobs.paper_quant_plan import generate_nextday_plan
    from src.ops.application.jobs.paper_quant_support import save_live_pool

    previous = [
        {"code": "000859", "name": "国风新材", "intent": "observe", "score": 73},
        {"code": "000603", "name": "盛达资源", "intent": "observe", "score": 63},
        {"code": "600664", "name": "哈药股份", "intent": "observe", "score": 61},
        {"code": "600721", "name": "百花医药", "intent": "observe", "score": 61},
    ]
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin("dragon-return")
        save_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-11",
            picks=previous,
        )
        before = store.get_setting("unified_monitor_pool:dragon-return", None)
        plan = generate_nextday_plan(
            store,
            slug="dragon-return",
            picks=previous,
            source="paper_eod",
            plan_date="2026-08-12",
            notify=False,
        )
        after = store.get_setting("unified_monitor_pool:dragon-return", None)

    assert plan["plan_date"] == "2026-08-12"
    assert [row["code"] for row in plan["items"]] == [row["code"] for row in previous]
    assert after == before

