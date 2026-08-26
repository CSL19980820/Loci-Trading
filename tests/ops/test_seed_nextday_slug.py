"""次日预案种子：仅 screen/skill；skill_watch 盘中禁止种子。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.ops.application.jobs.registry import _maybe_seed_nextday_plan
from src.ops.infrastructure.store import OpsStore


def test_seed_uses_config_skill_not_chinese_job_name(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.ensure_paper_cabin(
            "limit-up-momentum",
            config={"paper_quant": {"enabled": True}},
        )
        job = {
            "kind": "skill",
            "name": "选股·涨停动量",
            "config": {"skill": "limit-up-momentum"},
        }
        with patch(
            "src.ops.application.jobs.paper_quant.generate_nextday_plan",
            return_value={"plan_date": "2026-08-08", "id": "NDP-1"},
        ) as gen:
            _maybe_seed_nextday_plan(
                store=store,
                job=job,
                result={"picks": [{"code": "600001", "name": "测"}]},
            )
            assert gen.called
            assert gen.call_args.kwargs["slug"] == "limit-up-momentum"
            assert gen.call_args.kwargs["notify"] is False


def test_skill_watch_does_not_seed_nextday_plan(tmp_path: Path) -> None:
    """盘中监测不得改写/推送次日预案（收盘 paper_eod / 选股才写）。"""
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.ensure_paper_cabin(
            "dragon-return",
            config={"paper_quant": {"enabled": True}},
        )
        with patch(
            "src.ops.application.jobs.paper_quant.generate_nextday_plan"
        ) as gen:
            _maybe_seed_nextday_plan(
                store=store,
                job={
                    "kind": "skill_watch",
                    "name": "监测·龙回头",
                    "config": {"skill": "dragon-return"},
                },
                result={"picks": [{"code": "600001", "name": "测", "intent": "observe"}]},
            )
            assert gen.called is False


def test_screen_watch_picks_do_not_seed_opening_plan(tmp_path: Path) -> None:
    """低吸观察只留档展示，不能冒充次日开盘买入种子。"""
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.ensure_paper_cabin(
            "sanyuan-tail-v1",
            config={"paper_quant": {"enabled": True}},
        )
        with patch(
            "src.ops.application.jobs.paper_quant.generate_nextday_plan"
        ) as gen:
            _maybe_seed_nextday_plan(
                store=store,
                job={
                    "kind": "screen",
                    "name": "screen:sanyuan-tail-v1",
                    "config": {"strategy": "sanyuan-tail-v1"},
                },
                result={
                    "picks": [],
                    "watch_picks": [
                        {"code": "002963", "name": "豪尔赛", "intent": "observe"}
                    ],
                },
            )
            assert gen.called is False


def test_seed_refuses_chinese_job_name_fallback(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        before = {
            r["slug"] for r in store.conn.execute("SELECT slug FROM paper_cabins")
        }
        with patch(
            "src.ops.application.jobs.paper_quant.generate_nextday_plan"
        ) as gen:
            _maybe_seed_nextday_plan(
                store=store,
                job={
                    "kind": "skill",
                    "name": "监测·龙回头",
                    "config": {},
                },
                result={"picks": [{"code": "600001", "name": "测"}]},
            )
            assert gen.called is False
        after = {
            r["slug"] for r in store.conn.execute("SELECT slug FROM paper_cabins")
        }
        assert after == before
        assert "监测·龙回头" not in after
