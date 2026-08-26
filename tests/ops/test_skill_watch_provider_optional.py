"""P1-1：skill_watch 仅在 watch_use_ai 时强制 LLM。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.ops.application.jobs.context import JobContext, JobError
from src.ops.application.jobs.paper_quant_support import _today
from src.ops.application.jobs.skill_watch import execute_skill_watch
from src.ops.application.unified_monitor_pool import get_unified_monitor_pool
from src.ops.infrastructure.store import OpsStore


def test_skill_watch_allows_missing_provider_without_ai() -> None:
    store = MagicMock()
    with patch(
        "src.ops.application.jobs.skill_watch.run_skill_watch",
        return_value={"signals": []},
    ) as run:
        out = execute_skill_watch({"watch_use_ai": False}, JobContext(ops_store=store))
    assert out == {"signals": []}
    run.assert_called_once()


def test_skill_watch_requires_provider_when_ai_enabled() -> None:
    with pytest.raises(JobError, match="AI 摘要"):
        execute_skill_watch(
            {"watch_use_ai": True, "provider": ""},
            JobContext(ops_store=MagicMock()),
        )


def test_dragon_watch_runs_paper_actions_in_same_job(tmp_path, monkeypatch) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin(
            "dragon-return",
            config={"paper_quant": {"enabled": True}},
        )
        monkeypatch.setattr(
            "src.ops.application.jobs.skill_watch.run_skill_watch",
            lambda *_a, **_k: {
                "slug": "dragon-return",
                "summary": "扫描池：百花医药",
                "picks": [{"code": "600721", "name": "百花医药"}],
            },
        )

        def _monitor(config, _context):
            assert config["trigger"] == "skill_watch"
            # 扫描摘要不推企微时，纸面动作必须自己出声，否则成交回执会丢
            assert config["emit_follow"] is True
            assert config["collect_follow"] is True
            return {
                "status": "success",
                "follow_body": "✓持有 百花医药",
            }

        monkeypatch.setattr(
            "src.ops.application.jobs.paper_quant_monitor.execute_strategy_monitor",
            _monitor,
        )
        result = execute_skill_watch(
            {
                "skill": "dragon-return",
                "paper_monitor_slug": "dragon-return",
                "watch_use_ai": False,
            },
            JobContext(ops_store=store),
        )

    assert result["paper_monitor"]["status"] == "success"
    assert "扫描池：百花医药" in result["summary"]
    assert "✓持有 百花医药" in result["summary"]


def test_scan_summary_pushed_by_job_keeps_actions_in_one_message(
    tmp_path, monkeypatch
) -> None:
    """扫描摘要要推企微时，纸面动作并进同一条，别让同一轮发两遍。"""
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin(
            "dragon-return",
            config={"paper_quant": {"enabled": True}},
        )
        monkeypatch.setattr(
            "src.ops.application.jobs.skill_watch.run_skill_watch",
            lambda *_a, **_k: {
                "slug": "dragon-return",
                "trade_date": _today(),
                "summary": "👀观察 2：税友股份 | 观察龙头",
                "picks": [],
                "signals": [],
            },
        )

        def _monitor(config, _context):
            assert config["emit_follow"] is False
            return {
                "status": "success",
                "follow_body": "🔔纪律结果：1只开盘预案不买，本轮无成交",
            }

        monkeypatch.setattr(
            "src.ops.application.jobs.paper_quant_monitor.execute_strategy_monitor",
            _monitor,
        )
        result = execute_skill_watch(
            {
                "skill": "dragon-return",
                "paper_monitor_slug": "dragon-return",
                "push_wecom": True,
                "watch_use_ai": False,
            },
            JobContext(ops_store=store),
        )

    assert "👀观察 2：税友股份 | 观察龙头" in result["summary"]
    assert "🔔纪律结果：1只开盘预案不买，本轮无成交" in result["summary"]
