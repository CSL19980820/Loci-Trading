"""board live persist：写鉴权、默认只读、热库镜像。"""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.app.main import create_app
from src.market import MarketStore


def _seed_board_instrument(market_db: Path, hot_db: Path) -> None:
    instrument = {
        "code": "600519",
        "name": "贵州茅台",
        "market": "SH",
        "instrument_type": "STOCK",
    }
    for path in (market_db, hot_db):
        with MarketStore(str(path)) as store:
            store.upsert_instruments([instrument])


@pytest.fixture
def board_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    base = tmp_path / "data"
    base.mkdir()
    market_db = base / "market.db"
    hot_db = base / "market_hot.db"
    monkeypatch.setenv("PALACE_MARKET_DB", str(market_db))
    monkeypatch.setenv("PALACE_MARKET_HOT_DB", str(hot_db))
    monkeypatch.delenv("PALACE_ENABLE_SCHEDULER", raising=False)
    _seed_board_instrument(market_db, hot_db)
    app = create_app(base / "palace.db", base / "no-static")
    client = TestClient(app)
    yield client
    client.close()


def test_live_without_persist_does_not_write(board_client: TestClient) -> None:
    persisted = threading.Event()
    with (
        patch(
            "src.market.application.live.fetch_live_quotes",
            return_value=[
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "price": 1500.0,
                    "pct": 1.2,
                    "change": 18.0,
                    "prev_close": 1482.0,
                }
            ],
        ),
        patch("src.market.apply_today_spot", side_effect=lambda *_a, **_k: persisted.set() or 1),
        patch("src.market.api.board_router.board_spot_persist_gate", return_value=True),
    ):
        response = board_client.get("/api/market/board?live=true&page_size=1")

    assert response.status_code == 200, response.text
    assert not persisted.wait(timeout=0.3)


def test_persist_triggers_spot_and_hot_mirror(board_client: TestClient) -> None:
    persisted = threading.Event()
    mirrored = threading.Event()

    def fake_apply(*_args, **_kwargs) -> int:
        persisted.set()
        return 1

    def fake_mirror(*_args, **_kwargs) -> dict[str, object]:
        mirrored.set()
        return {"quotes": 1, "mode": "incremental", "end": "2026-07-31"}

    with (
        patch(
            "src.market.application.live.fetch_live_quotes",
            return_value=[
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "price": 1500.0,
                    "pct": 1.2,
                    "change": 18.0,
                    "prev_close": 1482.0,
                }
            ],
        ),
        patch("src.market.api.board_router.board_spot_persist_gate", return_value=True),
        patch("src.market.apply_today_spot", side_effect=fake_apply),
        patch("src.market.mirror_recent_to_hot", side_effect=fake_mirror),
    ):
        response = board_client.get(
            "/api/market/board?live=true&persist=true&page_size=1"
        )

    assert response.status_code == 200, response.text
    assert persisted.wait(timeout=2), "persist=true 应触发 apply_today_spot"
    assert mirrored.wait(timeout=2), "spot 落盘后应镜像热库"


def test_persist_without_live_is_rejected(board_client: TestClient) -> None:
    response = board_client.get("/api/market/board?persist=true")
    assert response.status_code == 422


def test_persist_requires_write_auth_when_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """强制写鉴权时未登录 persist 应 401（用 REQUIRE_WRITE_AUTH，免全套 production 凭证）。"""
    base = tmp_path / "auth"
    base.mkdir()
    market_db = base / "market.db"
    hot_db = base / "market_hot.db"
    monkeypatch.setenv("PALACE_ENV", "local")
    monkeypatch.setenv("PALACE_REQUIRE_WRITE_AUTH", "1")
    monkeypatch.setenv("PALACE_MARKET_DB", str(market_db))
    monkeypatch.setenv("PALACE_MARKET_HOT_DB", str(hot_db))
    monkeypatch.delenv("PALACE_ENABLE_SCHEDULER", raising=False)
    _seed_board_instrument(market_db, hot_db)

    app = create_app(base / "palace.db", base / "no-static")
    client = TestClient(app)
    try:
        with patch(
            "src.market.application.live.fetch_live_quotes",
            return_value=[
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "price": 1500.0,
                    "pct": 1.2,
                }
            ],
        ):
            response = client.get(
                "/api/market/board?live=true&persist=true&page_size=1"
            )
        assert response.status_code == 401
    finally:
        client.close()
