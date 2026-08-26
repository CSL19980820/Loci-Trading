from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.market import MarketStore, make_legacy_tape_call
from src.market.domain.tape import TapeRequest, TapeResult
from src.market.infrastructure.adapters.types import TAPE_LANES
from src.market.infrastructure.tape.local_provider import LocalTapeProvider
from src.market.infrastructure.tape.registry import reset_registry
from src.ops.application.skill_watch import dragon_return, leader_map, market_regime
from src.ops.application.skill_watch.auction_confirm import evaluate_auction
from src.ops.application.skill_watch.dragon_return import scan_dragon_return
from src.ops.application.skill_watch.market_regime import scan_market_gate
from src.ops.application.skill_watch.runner import run_skill_watch


class _LocalFakeProvider:
    provider_id = "local_fake"
    lanes = TAPE_LANES

    def fetch(self, request: TapeRequest) -> TapeResult:
        return TapeResult(
            data={
                "actualTradeDate": request.requested_date,
                "dateStatus": "exact",
                "rows": [],
            }
        )


class _DragonTapeProvider(_LocalFakeProvider):
    def fetch(self, request: TapeRequest) -> TapeResult:
        payloads = {
            "market_emotion": {
                "promotion_rate": 0.46,
                "broken_rate": 0.12,
                "breadth": 0.62,
                "temperature": 72,
            },
            "limit_up_pool": {
                "rows": [{"code": "600001", "name": "测试龙", "level": 3}]
            },
            "theme_board": {
                "rows": [
                    {"themeCode": "801843k", "themeName": "机器人", "strength": 82}
                ]
            },
            "theme_members": {"rows": [{"code": "600001", "name": "测试龙"}]},
            "auction_snapshot": {"active": False, "stances": []},
            "broken_limit_up": {"rows": []},
        }
        return TapeResult(data=payloads[request.lane])


class _MemoryMarketStore:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def history(self, _code: str, **_kwargs: object) -> pd.DataFrame:
        return self.frame.copy()


def _dragon_frame() -> pd.DataFrame:
    close = [10.0] * 20 + [11.0, 12.0, 13.0] + [11.0] * 5 + [12.5]
    volume = [1_000_000.0] * 23 + [200_000.0] * 5 + [1_500_000.0]
    start = date.today() - timedelta(days=len(close) - 1)
    return pd.DataFrame(
        {
            "date": [(start + timedelta(days=index)).isoformat() for index in range(len(close))],
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": volume,
            "amount": [price * vol for price, vol in zip(close, volume, strict=True)],
        }
    )


def test_runner_scans_with_local_provider_when_wudao_is_unavailable(
    monkeypatch,
) -> None:
    skill = {
        "slug": "demo",
        "name": "示例战法",
        "enabled": True,
        "metadata": {"signal_engine": "leader_map", "signals": ["watch_only"]},
    }
    monkeypatch.setattr(
        "src.ops.application.skills.resolve_skill",
        lambda slug: skill if slug == "demo" else None,
    )
    monkeypatch.setattr(
        "src.ops.application.skill_watch.runner.wudao_availability_for_watch",
        lambda: {"available": False, "reason": "悟道 MCP 未配置 API Key"},
    )

    def scanner(call_tool: Any, **_kwargs: Any) -> dict[str, Any]:
        payload = call_tool(
            "short_term_emotion",
            {"tradeDate": "2026-08-07", "format": "json"},
        )
        return {
            "signals": [],
            "picks": [],
            "trade_date": "2026-08-07",
            "market_gate": {
                "state": "empty",
                "entry_allowed": False,
                "data_status": "degraded",
                "quality_warnings": [],
                "provider_id": payload["provider_id"],
                "provider_ids": {"market_emotion": payload["provider_id"]},
            },
        }

    monkeypatch.setattr(
        "src.ops.application.skill_watch.runner._load_scanner",
        lambda _engine: scanner,
    )
    reset_registry([_LocalFakeProvider()])
    try:
        result = run_skill_watch({"skill": "demo"})
    finally:
        reset_registry(None)

    assert result.get("skipped") is not True
    assert result["available"] is True
    assert result["provider_id"] == "local_fake"
    assert result["signals"] == []


def test_dragon_scan_keeps_running_through_tape_bridge_without_wudao() -> None:
    reset_registry([_DragonTapeProvider()])
    try:
        result = scan_dragon_return(
            make_legacy_tape_call(),
            market_store=_MemoryMarketStore(_dragon_frame()),
        )
    finally:
        reset_registry(None)

    assert result["market_gate"]["state"] == "dragon"
    assert result["market_gate"]["provider_id"] == "local_fake"
    assert result["leader_map"]["leaders"]


def test_gate_fails_closed_when_every_tape_provider_is_disabled() -> None:
    reset_registry([])
    try:
        result = scan_market_gate()
    finally:
        reset_registry(None)

    assert result["state"] == "empty"
    assert result["entry_allowed"] is False
    assert result["provider_id"] is None
    assert result["data_status"] == "degraded"


def test_dragon_return_builds_local_theme_roles_without_wudao(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = MarketStore(tmp_path / "market.db")
    try:
        store.upsert_instruments(
            [{"code": "600001", "name": "本地龙", "industry": "本地科技"}]
        )
        bars = []
        for index in range(30):
            day = (date(2026, 7, 9) + timedelta(days=index)).isoformat()
            close = 11.0 if index == 28 else 12.1 if index == 29 else 10.0
            bars.append(
                {
                    "code": "600001",
                    "date": day,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000_000,
                    "amount": close * 1_000_000,
                }
            )
        store.upsert_quote_bars(bars)
        for module in (dragon_return, leader_map, market_regime):
            monkeypatch.setattr(module, "today_trade_date", lambda: "2026-08-07")
        monkeypatch.setattr(
            "src.ops.application.skills.resolve_skill",
            lambda slug: {
                "slug": slug,
                "name": "本地龙测试",
                "enabled": True,
                "metadata": {"signal_engine": "dragon_return"},
            },
        )
        monkeypatch.setattr(
            "src.ops.application.skill_watch.runner.wudao_availability_for_watch",
            lambda: {"available": False, "reason": "disabled in test"},
        )

        reset_registry([LocalTapeProvider(store)])
        try:
            result = run_skill_watch(
                {
                    "skill": "demo",
                    "tuning": {"stages": {"auction_confirm": False}},
                },
                market_store=store,
            )
        finally:
            reset_registry(None)
    finally:
        store.close()

    assert result["market_gate"]["state"] == "observe"
    assert result["market_gate"]["entry_allowed"] is False
    assert result["market_gate"]["provider_ids"]["theme_board"] == "local"
    assert result["market_gate"]["tape_provenance"]["theme_board"]["degraded"] is True
    assert any(
        "软降级" in str(reason)
        for reason in (result["market_gate"].get("reasons") or [])
    ) or "软降级" in str(result["market_gate"].get("reason") or "")
    assert result["tape_readiness"].get("skipped") is True
    assert result["entries"][0]["code"] == "600001"
    assert result["leader_map"]["leaders"]
    assert "local_industry_derived" in str(result["market_gate"]["quality_warnings"])


def test_unavailable_local_auction_is_pending_not_fabricated() -> None:
    stances = evaluate_auction(
        [{"code": "600001", "name": "本地龙"}],
        {
            "degraded": True,
            "unavailable": True,
            "provenance": {"provider_id": None, "degraded": True},
        },
    )

    assert stances[0]["stance"] == "pending"
    assert stances[0]["gap_pct"] is None
    assert stances[0]["reason"] == "竞价数据未就绪"
