"""手工纸面下单：非交易日 / 日历缺失买入 fail-closed → 409。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ops.api.paper_quant import build_paper_quant_router
from src.ops.infrastructure.store import OpsStore


def _client(ops_db: Path) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_paper_quant_router(write_dependency=lambda: None, ops_db=str(ops_db))
    )
    return TestClient(app, raise_server_exceptions=False)


def test_manual_buy_weekend_returns_409(tmp_path: Path) -> None:
    ops_db = tmp_path / "ops.db"
    with OpsStore(ops_db) as store:
        store.ensure_paper_cabin("demo")

    gate = {
        "trade_date": "2026-08-08",
        "is_trading_day": False,
        "buy_execution_allowed": False,
        "calendar_source": "market_db",
        "note": "2026-08-08 非交易日（周末/法定假日），跳过开仓与监测落单",
    }
    with (
        patch(
            "src.ops.application.jobs.paper_quant_support.resolve_trading_day_gate",
            return_value=gate,
        ),
        patch(
            "src.ops.application.jobs.paper_quant_support._today",
            return_value="2026-08-08",
        ),
        patch(
            "src.market.application.live_cache.get_cached_quotes",
            return_value=({}, {}, {}),
        ),
    ):
        with _client(ops_db) as client:
            response = client.post(
                "/api/ops/paper-cabins/demo/orders",
                json={
                    "orders": [
                        {"code": "600519", "action": "open", "layers": 0.5, "reason": "t"}
                    ]
                },
            )

    assert response.status_code == 409
    assert "非交易日" in response.json()["detail"]


def test_manual_buy_calendar_missing_fail_closed_409(tmp_path: Path) -> None:
    ops_db = tmp_path / "ops.db"
    with OpsStore(ops_db) as store:
        store.ensure_paper_cabin("demo")

    gate = {
        "trade_date": "2026-08-07",
        "is_trading_day": True,
        "buy_execution_allowed": False,
        "calendar_source": "weekday_fallback",
        "note": "2026-08-07 工作日但交易日历缺失：买入 fail-closed；监测可纠偏但不落买入成交",
    }
    with (
        patch(
            "src.ops.application.jobs.paper_quant_support.resolve_trading_day_gate",
            return_value=gate,
        ),
        patch(
            "src.ops.application.jobs.paper_quant_support._today",
            return_value="2026-08-07",
        ),
        patch(
            "src.market.application.live_cache.get_cached_quotes",
            return_value=({}, {}, {}),
        ),
    ):
        with _client(ops_db) as client:
            response = client.post(
                "/api/ops/paper-cabins/demo/orders",
                json={
                    "orders": [
                        {"code": "600519", "action": "open", "layers": 0.5, "reason": "t"}
                    ]
                },
            )

    assert response.status_code == 409
    assert "fail-closed" in response.json()["detail"]
