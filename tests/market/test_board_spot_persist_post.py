"""POST /api/market/board/spot：显式落盘与写鉴权。"""
from __future__ import annotations

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


def test_post_spot_triggers_apply_and_mirror(board_client: TestClient) -> None:
    calls: list[str] = []

    def fake_apply(*_args, **_kwargs) -> int:
        calls.append("apply")
        return 1

    def fake_mirror(*_args, **_kwargs) -> dict[str, object]:
        calls.append("mirror")
        return {"quotes": 1, "mode": "incremental", "end": "2026-07-31"}

    with (
        patch("src.market.apply_today_spot", side_effect=fake_apply),
        patch("src.market.mirror_recent_to_hot", side_effect=fake_mirror),
    ):
        response = board_client.post(
            "/api/market/board/spot",
            json={"codes": ["600519"]},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["written"] == 1
    assert "600519" in body["codes"]
    assert calls == ["apply", "mirror"]


def test_post_spot_page_without_codes(board_client: TestClient) -> None:
    with (
        patch("src.market.apply_today_spot", return_value=1) as apply_mock,
        patch(
            "src.market.mirror_recent_to_hot",
            return_value={"quotes": 1, "mode": "incremental"},
        ),
    ):
        response = board_client.post(
            "/api/market/board/spot",
            json={"page": 1, "page_size": 1},
        )

    assert response.status_code == 200, response.text
    assert apply_mock.called
    assert apply_mock.call_args.args[1] == ["600519"]


def test_post_spot_requires_write_auth_when_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQUIRE_WRITE_AUTH 时未登录 POST 应 401。"""
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
        response = client.post(
            "/api/market/board/spot",
            json={"codes": ["600519"]},
        )
        assert response.status_code == 401
    finally:
        client.close()


def test_post_spot_empty_universe_rejected(board_client: TestClient) -> None:
    response = board_client.post(
        "/api/market/board/spot",
        json={"codes": ["999999"]},
    )
    assert response.status_code == 422
