"""strategy_monitor：规则退出 + 模型失语验收。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.ops.application.jobs.context import JobContext
from src.ops.application.jobs.paper_quant_monitor import execute_strategy_monitor
from src.ops.application.jobs.paper_quant_support import save_live_pool
from src.ops.infrastructure.store import OpsStore


@dataclass
class _Snap:
    quotes: dict[str, dict[str, Any]]
    fetched_at: str = "2026-08-07T10:00:00+08:00"
    adapter_ids: list[str] | None = None
    cache_hits: int = 0


def _trading_gate_ok() -> dict[str, Any]:
    return {
        "is_trading_day": True,
        "buy_execution_allowed": True,
        "note": "test",
        "calendar_source": "test",
    }


def _market_gate_ok() -> dict[str, Any]:
    return {"entry_allowed": True, "mode": "龙"}


def _cabin_with_stop_position(store: OpsStore, *, cfg: dict[str, Any]) -> str:
    cabin = store.ensure_paper_cabin("demo", max_layers=2.0)
    store.update_paper_cabin_config("demo", cfg)
    store.upsert_paper_position(
        cabin["id"],
        code="600519",
        name="茅台",
        layers=1.0,
        mark_cost=100.0,
    )
    store.upsert_nextday_plan(
        {
            "slug": "demo",
            "plan_date": "2026-08-07",
            "items": [],
            "body_text": "",
        }
    )
    return str(cabin["id"])


@patch("src.ops.application.jobs.paper_quant_monitor.dispatch_text", return_value={"sent": False})
@patch(
    "src.ops.application.jobs.paper_quant_support._resolve_market_gate",
    return_value=_market_gate_ok(),
)
@patch(
    "src.ops.application.jobs.paper_quant_support.resolve_trading_day_gate",
    return_value=_trading_gate_ok(),
)
@patch("src.ops.application.jobs.paper_quant_support._today", return_value="2026-08-07")
@patch("src.market.application.live_cache.build_monitor_snapshot")
def test_strategy_monitor_rules_mode_stop_cut(
    mock_snap: Any,
    _mock_today: Any,
    _mock_gate: Any,
    _mock_mkt: Any,
    _mock_push: Any,
    tmp_path: Path,
) -> None:
    """ai_mode=rules 且持仓跌破止损线时应落 stop_cut 成交。"""
    mock_snap.return_value = _Snap(
        quotes={"600519": {"price": 93.0, "name": "茅台", "prev_close": 100.0}}
    )
    db = tmp_path / "ops.db"
    cabin_id = ""
    with OpsStore(db) as store:
        cabin_id = _cabin_with_stop_position(
            store,
            cfg={
                "enabled": True,
                "ai_mode": "rules",
                "ai_apply_paper": True,
                "follow_wecom": False,
                "stop_loss_pct": -6.0,
                "rules_exit_enabled": True,
            },
        )
        out = execute_strategy_monitor({"slug": "demo", "force": True}, JobContext(ops_store=store))

    assert out.get("skipped") is not True
    assert out.get("fills") == 1
    assert "rules 退出" in str(out.get("notes") or "")
    with OpsStore(db) as store:
        positions = store.list_paper_positions(cabin_id)
    assert positions == []


@patch("src.ops.application.jobs.paper_quant_monitor.dispatch_text", return_value={"sent": True})
@patch(
    "src.ops.application.jobs.paper_quant_support._resolve_market_gate",
    return_value=_market_gate_ok(),
)
@patch(
    "src.ops.application.jobs.paper_quant_support.resolve_trading_day_gate",
    return_value=_trading_gate_ok(),
)
@patch("src.ops.application.jobs.paper_quant_support._today", return_value="2026-08-07")
@patch("src.market.application.live_cache.build_monitor_snapshot")
def test_strategy_monitor_suggest_no_model_still_rules_exit_stop_cut(
    mock_snap: Any,
    _mock_today: Any,
    _mock_gate: Any,
    _mock_mkt: Any,
    _mock_push: Any,
    tmp_path: Path,
) -> None:
    """P0-2：ai_mode=suggest 且无 model 时仍应走规则退出产出 stop_cut。"""
    mock_snap.return_value = _Snap(
        quotes={"600519": {"price": 93.0, "name": "茅台", "prev_close": 100.0}}
    )
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        _cabin_with_stop_position(
            store,
            cfg={
                "enabled": True,
                "ai_mode": "suggest",
                "model": "",
                "ai_apply_paper": True,
                "follow_wecom": False,
                "stop_loss_pct": -6.0,
                "rules_exit_enabled": True,
            },
        )
        out = execute_strategy_monitor({"slug": "demo", "force": True}, JobContext(ops_store=store))

    assert out.get("skipped") is not True
    assert out.get("fills") == 1
    assert "rules 退出" in str(out.get("notes") or "")
    assert "stop_cut" in str(out.get("notes") or "") or out.get("fills") == 1
    with OpsStore(db) as store:
        runs = store.list_monitor_runs("demo", limit=1)
        fills = list((runs[0] if runs else {}).get("fills") or [])
    assert fills and fills[0].get("action") == "stop_cut"


@pytest.mark.parametrize(
    ("include_position_lines", "shows_position"),
    [(True, True), (False, False)],
)
@patch("src.ops.application.jobs.paper_quant_monitor.dispatch_text", return_value={"sent": False})
@patch(
    "src.ops.application.jobs.paper_quant_support._resolve_market_gate",
    return_value=_market_gate_ok(),
)
@patch(
    "src.ops.application.jobs.paper_quant_support.resolve_trading_day_gate",
    return_value=_trading_gate_ok(),
)
@patch("src.ops.application.jobs.paper_quant_support._today", return_value="2026-08-07")
@patch("src.market.application.live_cache.build_monitor_snapshot")
def test_follow_body_uses_position_facts_not_llm_prose(
    mock_snap: Any,
    _mock_today: Any,
    _mock_gate: Any,
    _mock_mkt: Any,
    _mock_push: Any,
    tmp_path: Path,
    include_position_lines: bool,
    shows_position: bool,
) -> None:
    mock_snap.return_value = _Snap(
        quotes={
            "600519": {
                "price": 110.0,
                "open": 101.0,
                "name": "茅台",
                "prev_close": 100.0,
            }
        }
    )
    with OpsStore(tmp_path / "ops.db") as store:
        cabin = store.ensure_paper_cabin("demo", max_layers=2.0)
        store.update_paper_cabin_config(
            "demo",
            {
                "enabled": True,
                "ai_mode": "suggest",
                "model": "fake-model",
                "ai_apply_paper": True,
                "follow_wecom": False,
            },
        )
        store.upsert_paper_position(
            cabin["id"],
            code="600519",
            name="茅台",
            layers=1.0,
            mark_cost=100.0,
        )
        with patch(
            "src.ops.application.jobs.paper_quant_monitor._call_monitor_llm",
            return_value=(
                '{"orders":[],"notes":"市场看起来还可以，继续耐心观察，'
                '不要着急，等待后续走势确认。"}'
            ),
        ):
            out = execute_strategy_monitor(
                {
                    "slug": "demo",
                    "force": True,
                    "collect_follow": True,
                    "include_position_lines": include_position_lines,
                },
                JobContext(ops_store=store),
            )

    body = str(out.get("follow_body") or "")
    assert ("📦茅台 · 1层 · 成本100 · +10.0%" in body) is shows_position
    assert ("👀持仓巡检" in body) is shows_position
    assert "市场看起来还可以" not in body
    assert "继续耐心观察" not in body


def _aphasia_harness(
    *,
    llm_text: str,
    tmp_path: Path,
    mock_snap: Any,
    mock_push: MagicMock,
) -> dict[str, Any]:
    mock_snap.return_value = _Snap(
        quotes={"600519": {"price": 100.0, "name": "茅台", "prev_close": 100.0}}
    )
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.ensure_paper_cabin("demo", max_layers=2.0)
        store.update_paper_cabin_config(
            "demo",
            {
                "enabled": True,
                "ai_mode": "suggest",
                "model": "fake-model",
                "ai_apply_paper": True,
                "follow_wecom": False,
            },
        )
        store.upsert_paper_position(
            store.ensure_paper_cabin("demo")["id"],
            code="600519",
            name="茅台",
            layers=1.0,
            mark_cost=100.0,
        )
        with patch(
            "src.ops.application.jobs.paper_quant_monitor._call_monitor_llm",
            return_value=llm_text,
        ):
            out = execute_strategy_monitor(
                {"slug": "demo", "force": True},
                JobContext(ops_store=store),
            )
    assert out.get("status") == "failed"
    assert out.get("fills") == 0
    assert "未产出可执行" in str(out.get("notes") or "")
    mock_push.assert_called()
    body = " ".join(
        str(c.kwargs.get("body") or (c.args[1] if len(c.args) > 1 else "") or "")
        for c in mock_push.call_args_list
    )
    # dispatch_text(store, title=..., body=...)
    if not body.strip():
        bodies = []
        for c in mock_push.call_args_list:
            if c.kwargs.get("body"):
                bodies.append(str(c.kwargs["body"]))
            elif len(c.args) >= 3:
                bodies.append(str(c.args[2]))
        body = " ".join(bodies)
    assert "失语" in body or "未产出可执行" in body
    return out


@patch("src.ops.application.jobs.paper_quant_monitor.dispatch_text", return_value={"sent": True})
@patch(
    "src.ops.application.jobs.paper_quant_support._resolve_market_gate",
    return_value=_market_gate_ok(),
)
@patch(
    "src.ops.application.jobs.paper_quant_support.resolve_trading_day_gate",
    return_value=_trading_gate_ok(),
)
@patch("src.ops.application.jobs.paper_quant_support._today", return_value="2026-08-07")
@patch("src.market.application.live_cache.build_monitor_snapshot")
def test_strategy_monitor_llm_empty_text_fails_and_alerts(
    mock_snap: Any,
    _mock_today: Any,
    _mock_gate: Any,
    _mock_mkt: Any,
    mock_push: Any,
    tmp_path: Path,
) -> None:
    """P0-1：空 completion → failed + fills 空 + 企微含失语。"""
    _aphasia_harness(llm_text="", tmp_path=tmp_path, mock_snap=mock_snap, mock_push=mock_push)


@patch("src.ops.application.jobs.paper_quant_monitor.dispatch_text", return_value={"sent": True})
@patch(
    "src.ops.application.jobs.paper_quant_support._resolve_market_gate",
    return_value=_market_gate_ok(),
)
@patch(
    "src.ops.application.jobs.paper_quant_support.resolve_trading_day_gate",
    return_value=_trading_gate_ok(),
)
@patch("src.ops.application.jobs.paper_quant_support._today", return_value="2026-08-07")
@patch("src.market.application.live_cache.build_monitor_snapshot")
def test_strategy_monitor_llm_prose_non_json_fails_and_alerts(
    mock_snap: Any,
    _mock_today: Any,
    _mock_gate: Any,
    _mock_mkt: Any,
    mock_push: Any,
    tmp_path: Path,
) -> None:
    """P0-1：散文非 JSON → failed + fills 空 + 企微含失语。"""
    _aphasia_harness(
        llm_text="今天市场不错。",
        tmp_path=tmp_path,
        mock_snap=mock_snap,
        mock_push=mock_push,
    )


@pytest.mark.parametrize(
    ("configured_timeout", "expected_timeout"),
    [(None, 1800.0), (60, 120.0), (1800, 1800.0), (3600, 1800.0)],
)
def test_strategy_monitor_honors_cabin_llm_timeout(
    tmp_path: Path,
    configured_timeout: float | None,
    expected_timeout: float,
) -> None:
    """纸面舱慢推理预算默认 30 分钟，并限制在 2–30 分钟。"""
    from src.ai import ProviderConfig

    captured: list[float] = []

    def fake_chat(config: ProviderConfig, *_args: Any, **_kwargs: Any) -> str:
        captured.append(float(config.timeout))
        return '{"orders": [], "notes": "继续观察"}'

    def fake_resolve(*_args: Any, timeout: float | None = None, **_kwargs: Any) -> ProviderConfig:
        return ProviderConfig(
            name="slow",
            protocol="openai_compatible",
            base_url="https://example.test",
            api_key="test-key",
            model="slow-model",
            timeout=float(timeout or 120.0),
        )

    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        _cabin_with_stop_position(
            store,
            cfg={
                "enabled": True,
                "ai_mode": "suggest",
                "model": "slow-model",
                "ai_apply_paper": True,
                "follow_wecom": False,
                "llm_timeout_sec": configured_timeout,
            },
        )
        with (
            patch(
                "src.ops.application.jobs.paper_quant_support._today",
                return_value="2026-08-07",
            ),
            patch(
                "src.ops.application.jobs.paper_quant_support.resolve_trading_day_gate",
                return_value=_trading_gate_ok(),
            ),
            patch(
                "src.ops.application.jobs.paper_quant_support._resolve_market_gate",
                return_value=_market_gate_ok(),
            ),
            patch(
                "src.market.application.live_cache.build_monitor_snapshot",
                return_value=_Snap(
                    quotes={
                        "600519": {
                            "price": 100.0,
                            "name": "茅台",
                            "prev_close": 100.0,
                        }
                    }
                ),
            ),
            patch(
                "src.ai.resolve_config",
                side_effect=fake_resolve,
            ),
            patch("src.ai.chat_text_with_thinking_fallback", side_effect=fake_chat),
            patch(
                "src.ops.application.jobs.paper_quant_monitor.dispatch_text",
                return_value={"sent": False},
            ),
        ):
            out = execute_strategy_monitor(
                {"slug": "demo", "force": True},
                JobContext(ops_store=store),
            )

    assert out["status"] == "success"
    assert captured == [expected_timeout]


def test_strategy_monitor_prefers_same_day_live_pool(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.ensure_paper_cabin("dragon-return")
        store.update_paper_cabin_config(
            "dragon-return",
            {"enabled": True, "ai_mode": "rules", "follow_wecom": False},
        )
        store.upsert_nextday_plan(
            {
                "slug": "dragon-return",
                "plan_date": "2026-08-10",
                "items": [
                    {
                        "code": "600829",
                        "name": "人民同泰",
                        "intent": "observe",
                        "score": 54,
                    }
                ],
                "body_text": "",
            }
        )
        save_live_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-10",
            picks=[
                {
                    "code": "600127",
                    "name": "金健米业",
                    "intent": "observe",
                    "score": 50,
                }
            ],
        )

        snap = _Snap(quotes={"600127": {"price": 8.0, "prev_close": 8.0}})
        with (
            patch(
                "src.ops.application.jobs.paper_quant_support._today",
                return_value="2026-08-10",
            ),
            patch(
                "src.ops.application.jobs.paper_quant_support.resolve_trading_day_gate",
                return_value=_trading_gate_ok(),
            ),
            patch(
                "src.ops.application.jobs.paper_quant_support._resolve_market_gate",
                return_value=_market_gate_ok(),
            ),
            patch(
                "src.market.application.live_cache.build_monitor_snapshot",
                return_value=snap,
            ),
            patch(
                "src.ops.application.jobs.paper_quant_monitor.dispatch_text",
                return_value={"sent": False},
            ),
        ):
            out = execute_strategy_monitor(
                {"slug": "dragon-return", "force": True},
                JobContext(ops_store=store),
            )

        assert out["status"] == "success"
        run = store.list_monitor_runs("dragon-return", limit=1)[0]
        assert run["snapshot"]["codes"] == ["600127"]


def test_strategy_monitor_does_not_reuse_stale_dragon_plan(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.ensure_paper_cabin("dragon-return")
        store.update_paper_cabin_config(
            "dragon-return",
            {"enabled": True, "ai_mode": "rules", "follow_wecom": False},
        )
        store.upsert_nextday_plan(
            {
                "slug": "dragon-return",
                "plan_date": "2026-08-10",
                "items": [
                    {
                        "code": "600829",
                        "name": "人民同泰",
                        "intent": "observe",
                        "score": 54,
                    }
                ],
                "body_text": "",
            }
        )
        with (
            patch(
                "src.ops.application.jobs.paper_quant_support._today",
                return_value="2026-08-10",
            ),
            patch(
                "src.ops.application.jobs.paper_quant_support.resolve_trading_day_gate",
                return_value=_trading_gate_ok(),
            ),
            patch(
                "src.ops.application.jobs.paper_quant_support._resolve_market_gate",
                return_value=_market_gate_ok(),
            ),
            patch("src.market.application.live_cache.build_monitor_snapshot") as snap,
        ):
            out = execute_strategy_monitor(
                {"slug": "dragon-return", "force": True},
                JobContext(ops_store=store),
            )

        assert out["skipped"] is True
        assert out["reason"] == "empty_universe"
        snap.assert_not_called()
