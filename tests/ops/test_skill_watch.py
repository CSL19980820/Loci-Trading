"""skill_watch：扫描器打分 + runner 编排（引擎解析、信号白名单）。"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from src.ops.application.jobs.paper_quant_support import load_live_pool, save_live_pool
from src.ops.application.skill_watch.dragon_return import score_pullback
from src.ops.application.skill_watch.kline_stats import trend_stats
from src.ops.application.skill_watch.runner import run_skill_watch
from src.ops.application.skill_watch.tuning import save_tuning
from src.ops.infrastructure.store import OpsStore


def test_score_dragon_prefers_pullback_restart() -> None:
    n = 40
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = [10.0] * 20 + [12.0] * 5 + [11.0] * 14 + [11.8]
    volume = [1_000_000.0] * 25 + [400_000.0] * 14 + [1_200_000.0]
    frame = pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in dates[: len(close)]],
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": volume[: len(close)],
            "amount": [0.0] * len(close),
        }
    )
    score, meta = score_pullback(trend_stats(frame, code="600001"))
    assert score >= 30
    assert meta["pullback_days"] >= 0


def test_trend_stats_uses_recent_stage_peak_for_pullback_buy_zone() -> None:
    recent = [10.0] * 10 + [12.0, 14.0, 16.0] + [14.0] * 5 + [15.0] * 3
    close = [20.0] + [10.0] * 39 + recent
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=len(close), freq="B").strftime(
                "%Y-%m-%d"
            ),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": [1_000_000.0] * len(close),
        }
    )

    stats = trend_stats(frame, code="600001")

    assert stats is not None
    assert stats["pullback_days"] == len(close) - 1
    assert stats["pullback_days_recent"] == 8
    assert stats["pullback_depth_pct"] == 12.5
    assert stats["pullback_drawdown_pct"] == 6.25


def test_dragon_return_only_keeps_leaders_and_promotes_limit_up_individuals() -> None:
    from src.ops.application.skill_watch.dragon_return import _rank_eligible

    def _entry(code: str, *, role: str, is_limit_up: bool, today_pct: float) -> dict[str, Any]:
        return {
            "code": code,
            "name": code,
            "close": 10.0,
            "ma10": 9.8,
            "ma20": 9.5,
            "drawdown_pct": 5.0,
            "pullback_days": 1,
            "pullback_days_recent": 1,
            "pullback_depth_pct": 5.0,
            "pullback_drawdown_pct": 2.0,
            "vol_shrink": 0.8,
            "today_pct": today_pct,
            "vol_ratio": 1.5,
            "strong_days": 3,
            "gain_20_pct": 30.0,
            "ladder_level": None,
            "role": role,
            "role_label": "龙头" if role == "leader" else "中军",
            "role_basis": "题材内角色",
            "theme_name": "医药",
            "is_limit_up": is_limit_up,
        }

    ranked = _rank_eligible(
        {
            "entries": [
                _entry("leader", role="leader", is_limit_up=False, today_pct=4.0),
                _entry("limit-up", role="secondary", is_limit_up=True, today_pct=9.96),
                _entry("secondary", role="secondary", is_limit_up=False, today_pct=4.0),
            ]
        }
    )

    assert {row["code"] for row in ranked} == {"leader", "limit-up"}
    promoted = next(row for row in ranked if row["code"] == "limit-up")
    assert promoted["role"] == "leader"
    assert promoted["role_label"] == "龙头"
    assert "个股涨停" in promoted["role_basis"]


def _install_skill(monkeypatch: pytest.MonkeyPatch, metadata: dict[str, Any]) -> None:
    skill = {"slug": "demo", "name": "示例战法", "enabled": True, "metadata": metadata}
    monkeypatch.setattr(
        "src.ops.application.skills.resolve_skill",
        lambda slug: skill if slug == "demo" else None,
    )


def _install_scanner(monkeypatch: pytest.MonkeyPatch, signals: list[dict[str, Any]]) -> None:
    monkeypatch.setattr(
        "src.ops.application.skill_watch.runner._load_scanner",
        lambda engine: (
            lambda call_tool, **_kwargs: {"signals": signals, "pool_size": 3}
        ),
    )


def test_run_skill_watch_keeps_only_declared_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_skill(monkeypatch, {"strategy_skill": True, "signals": ["buy_hint"]})
    _install_scanner(
        monkeypatch,
        [
            {"type": "buy_hint", "code": "600519", "score": 88},
            {"type": "sell_hint", "code": "000001", "score": 20},
        ],
    )
    result = run_skill_watch({"skill": "demo"}, call_tool=lambda *_: {})
    assert [s["type"] for s in result["signals"]] == ["buy_hint"]
    assert "候选" in result["summary"]
    assert "600519" in result["summary"]


def test_run_skill_watch_without_declared_signals_keeps_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_skill(monkeypatch, {"strategy_skill": True})
    _install_scanner(
        monkeypatch,
        [
            {"type": "buy_hint", "code": "600519"},
            {"type": "watch_only", "code": "000001"},
        ],
    )
    result = run_skill_watch({"skill": "demo"}, call_tool=lambda *_: {})
    assert len(result["signals"]) == 2


def test_run_skill_watch_skips_when_no_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_skill(monkeypatch, {"strategy_skill": True, "signal_engine": "unknown"})
    result = run_skill_watch({"skill": "demo"}, call_tool=lambda *_: {})
    assert result["skipped"] is True
    assert result["reason"] == "no_signal_engine"


def test_run_skill_watch_reports_no_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_skill(monkeypatch, {"strategy_skill": True})
    _install_scanner(monkeypatch, [])
    result = run_skill_watch({"skill": "demo"}, call_tool=lambda *_: {})
    assert result["summary"] == "无新信号"
    assert result["ai_summary"] == ""


@pytest.mark.parametrize(
    ("timeout_config", "expected"),
    [({}, 1800.0), ({"llm_timeout_sec": 600}, 600.0)],
)
def test_skill_watch_ai_summary_uses_shared_slow_llm_timeout(
    monkeypatch: pytest.MonkeyPatch,
    timeout_config: dict[str, Any],
    expected: float,
) -> None:
    from src.ai import ProviderConfig
    from src.ops.application.skill_watch.runner import _ai_summary

    captured: list[float] = []
    provider = ProviderConfig(
        name="slow",
        protocol="openai_compatible",
        base_url="https://example.invalid/v1",
        api_key="test",
        timeout=45.0,
    )
    monkeypatch.setattr("src.ai.resolve_config", lambda *_a, **_k: provider)

    def _chat(config: ProviderConfig, *_a: Any, **_k: Any) -> SimpleNamespace:
        captured.append(config.timeout)
        return SimpleNamespace(text="摘要")

    monkeypatch.setattr("src.ai.chat", _chat)

    result = _ai_summary(
        store=object(),
        skill={"slug": "demo", "name": "示例战法"},
        config={"provider": "slow", **timeout_config},
        signals=[{"type": "watch_only", "code": "600001", "title": "观察"}],
    )

    assert result == "摘要"
    assert captured == [expected]


def test_run_skill_watch_requires_slug() -> None:
    from src.ops.application.jobs.context import JobError

    with pytest.raises(JobError):
        run_skill_watch({}, call_tool=lambda *_: {})


def test_run_skill_watch_continues_with_local_fallback_without_wudao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_skill(monkeypatch, {"strategy_skill": True, "signal_engine": "leader_map"})
    monkeypatch.setattr(
        "src.ops.application.skill_watch.runner.wudao_availability_for_watch",
        lambda: {"available": False, "reason": "悟道 MCP 未配置 API Key"},
    )

    monkeypatch.setattr(
        "src.ops.application.skill_watch.runner._load_scanner",
        lambda _engine: (
            lambda _call_tool, **_kwargs: {
                "signals": [],
                "picks": [],
                "market_gate": {
                    "state": "empty",
                    "entry_allowed": False,
                    "data_status": "degraded",
                    "quality_warnings": ["local_fallback"],
                },
            }
        ),
    )

    result = run_skill_watch({"skill": "demo"})

    assert result.get("skipped") is not True
    assert result["available"] is True
    assert result["degraded"] is True


def test_run_skill_watch_keeps_filtered_picks_and_suggestions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """runner 出口的 picks/suggestions 不得被引擎 result 覆盖。"""
    _install_skill(monkeypatch, {"strategy_skill": True, "signal_engine": "dragon_return"})
    monkeypatch.setattr(
        "src.ops.application.skill_watch.runner._load_scanner",
        lambda engine: (
            lambda call_tool, **_kwargs: {
                "signals": [],
                "picks": [
                    {"code": "600519", "name": "茅台", "auction_stance": "confirmed"},
                    {
                        "code": "000001",
                        "name": "平安",
                        "auction_stance": "abandoned",
                        "role": "failed",
                        "role_basis": "竞价放弃",
                    },
                ],
            }
        ),
    )
    monkeypatch.setattr(
        "src.ops.application.skill_watch.role_stats.suggest_tuning_adjustments",
        lambda *_a, **_k: [
            {"direction": "tighten_weakened_drawdown", "message": "测试建议"},
        ],
    )

    class _Store:
        def list_leader_roles(self, *_a: Any, **_k: Any) -> list[dict[str, Any]]:
            return []

        def append_leader_roles(self, *_a: Any, **_k: Any) -> int:
            return 0

    result = run_skill_watch(
        {"skill": "demo"},
        call_tool=lambda *_: {},
        store=_Store(),
    )
    assert [p["code"] for p in result["picks"]] == ["600519"]
    assert "000001" in result["auction_excluded"]
    assert result["suggestions"]
    assert result["suggestions"][0]["direction"] == "tighten_weakened_drawdown"


def test_dragon_return_live_pool_keeps_uninvalidated_leader_across_theme_rotation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """旧龙仅因题材跌出前三不得消失；新票须按分差替换池内最弱票。"""
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
                "trade_date": "2026-08-10",
                "signals": [],
                "picks": [
                    {
                        "code": "000603",
                        "name": "盛达资源",
                        "intent": "observe",
                        "score": 77,
                        "role": "leader",
                        "role_label": "龙头",
                        "theme_name": "黄金",
                    },
                    {
                        "code": "603988",
                        "name": "中电电机",
                        "intent": "observe",
                        "score": 65,
                        "role": "leader",
                        "role_label": "龙头",
                        "theme_name": "并购重组",
                    },
                ],
                # 百花医药没有走弱证据，只是医药跌出当轮前三题材。
                "entries": [
                    {"code": "000603", "role": "leader"},
                    {"code": "603988", "role": "leader"},
                ],
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

    with OpsStore(tmp_path / "ops.db") as store:
        save_tuning(
            store,
            "dragon-return",
            {
                "scan": {
                    "max_observe_pool": 2,
                    "max_observe": 2,
                    "observe_replace_margin": 8,
                }
            },
        )
        store.ensure_paper_cabin("dragon-return")
        save_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
            picks=[
                {
                    "code": "600721",
                    "name": "百花医药",
                    "intent": "observe",
                    "score": 69,
                    "role": "leader",
                    "role_label": "龙头",
                    "theme_name": "医药",
                },
                {
                    "code": "600127",
                    "name": "金健米业",
                    "intent": "observe",
                    "score": 50,
                    "role": "secondary",
                    "role_label": "中军",
                    "theme_name": "食品饮料",
                },
            ],
        )

        result = run_skill_watch(
            {"skill": "dragon-return"},
            call_tool=lambda *_: {},
            store=store,
        )
        saved = load_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
        )

    assert [row["code"] for row in result["picks"]] == ["000603", "600721"]
    assert [row["code"] for row in saved or []] == ["000603", "600721"]


def test_dragon_return_live_pool_removes_explicitly_weakened_ticket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
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
                "trade_date": "2026-08-10",
                "signals": [],
                "picks": [],
                "entries": [
                    {
                        "code": "600721",
                        "name": "百花医药",
                        "role": "weakened",
                        "role_basis": "失守 MA10",
                    }
                ],
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

    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin("dragon-return")
        save_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
            picks=[
                {
                    "code": "600721",
                    "name": "百花医药",
                    "intent": "observe",
                    "score": 69,
                    "role": "leader",
                    "role_label": "龙头",
                }
            ],
        )
        result = run_skill_watch(
            {"skill": "dragon-return"},
            call_tool=lambda *_: {},
            store=store,
        )
        saved = load_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
        )

    assert result["picks"] == []
    assert saved == []
    dropped = result["observe_changes"]["dropped"][0]
    assert dropped["code"] == "600721"
    assert dropped["score"] == 69
    assert "👀 百花医药 600721（🗑️移出），69分，失守 MA10" in result["summary"]
    assert "🔄【观察池变更】" not in result["summary"]


def test_dragon_return_live_pool_drops_middle_but_keeps_promoted_limit_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
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
    promoted = {
        "code": "600721",
        "name": "百花医药",
        "intent": "observe",
        "score": 61,
        "role": "leader",
        "role_label": "龙头",
        "role_basis": "个股涨停，人气与涨幅强",
    }
    monkeypatch.setattr(
        "src.ops.application.skill_watch.runner._load_scanner",
        lambda _engine: (
            lambda _call_tool, **_kwargs: {
                "trade_date": "2026-08-11",
                "signals": [],
                "picks": [promoted],
                # 龙头地图的题材内原始角色仍是 secondary；ranked 是龙王个股强度纠偏结果。
                "entries": [
                    {
                        "code": "600721",
                        "name": "百花医药",
                        "role": "secondary",
                        "role_label": "中军",
                    }
                ],
                "ranked": [promoted],
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

    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin("dragon-return")
        save_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-11",
            picks=[
                {
                    "code": "600721",
                    "name": "百花医药",
                    "intent": "observe",
                    "score": 61,
                    "role": "secondary",
                    "role_label": "中军",
                },
                {
                    "code": "000506",
                    "name": "招金黄金",
                    "intent": "observe",
                    "score": 71,
                    "role": "secondary",
                    "role_label": "中军",
                },
            ],
        )
        result = run_skill_watch(
            {"skill": "dragon-return"},
            call_tool=lambda *_: {},
            store=store,
        )
        role_history = store.list_leader_roles("dragon-return")

    assert [(row["code"], row["role"]) for row in result["picks"]] == [
        ("600721", "leader")
    ]
    assert [(row["code"], row["role"]) for row in role_history] == [
        ("600721", "leader")
    ]
    assert result["observe_changes"]["dropped"][0]["code"] == "000506"
    assert "中军" in result["observe_changes"]["dropped"][0]["reason"]


def test_legacy_theme_rotation_engine_now_loads_leader_map() -> None:
    from src.ops.application.skill_watch.leader_map import scan_leader_map
    from src.ops.application.skill_watch.runner import _load_scanner

    for engine in ("theme_rotation", "theme-leader-rotation", "market-leader-map", "leader_map"):
        assert _load_scanner(engine) is scan_leader_map
