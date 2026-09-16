"""The current win-rate UI follows the workshop without deleting historical facts."""
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ledger import PalaceStore
from src.market import MarketStore
from src.ops import OpsStore
from src.review.api import router as router_module
from src.review.application.workshop import workshop_winrates


def test_catalog_order_names_new_and_deleted_strategies():
    rows = [{"strategy_tag": "deleted", "total": 99},
            {"strategy_tag": "yixian-auction", "total": 2, "wins": 1, "win_rate": 50}]
    before = deepcopy(rows)
    catalog = [{"slug": "new", "name": "新战法"},
               {"slug": "yixian-auction", "name": "一线定乾坤·首板次日"}]
    joined = workshop_winrates(rows, catalog)
    assert [row["strategy_tag"] for row in joined] == ["new", "yixian-auction"]
    assert joined[0]["win_rate"] is None and joined[0]["total"] == 0
    assert joined[1]["strategy_name"] == "一线定乾坤·首板次日"
    assert joined[1]["total"] == 2 and joined[1]["win_rate"] == 50
    assert rows == before
    assert workshop_winrates(rows, []) == []


def test_current_catalog_is_joined_after_statistics_cache(tmp_path, monkeypatch):
    with OpsStore(None) as store:
        for slug in ("custom", "new"):
            store.ensure_job(name=f"测试已启用战法-{slug}", kind="screen", cron="0 15 * * mon-fri",
                             enabled=True, config={"strategy": slug})
    rows = [{"strategy_tag": "custom", "total": 2}, {"strategy_tag": "deleted", "total": 100}]
    compute = Mock(return_value=rows)
    catalog = [{"slug": "custom", "name": "当前名称"}]
    monkeypatch.setattr("src.review.build_winrate_summary", compute)
    monkeypatch.setattr("src.strategy.describe_all", lambda: catalog)
    router_module.clear_review_cache()
    app = FastAPI()
    app.include_router(router_module.build_review_router(
        palace_db=str(tmp_path / "palace.db"), market_db=str(tmp_path / "market.db")))
    try:
        with TestClient(app) as client:
            url = "/api/winrate/summary?current_only=1"
            assert client.get(url).json()[0]["strategy_name"] == "当前名称"
            catalog[0]["name"] = "修改后的名称"
            assert client.get(url).json()[0]["strategy_name"] == "修改后的名称"
            catalog.clear()
            assert client.get(url).json() == []
            assert client.get("/api/winrate/summary").json() == rows
            catalog.append({"slug": "new", "name": "刚创建的战法"})
            assert client.get(url).json()[0]["win_rate"] is None
            assert compute.call_count == 1
    finally:
        router_module.clear_review_cache()


def test_cache_uses_actual_database_not_optional_router_arguments(tmp_path, monkeypatch):
    # Equal fingerprints in different tenant DBs must still occupy different keys.
    active = ["a"]
    @contextmanager
    def palace(_):
        with PalaceStore(tmp_path / f"{active[0]}.db") as store:
            yield store
    @contextmanager
    def market(_):
        with MarketStore(tmp_path / "market.db") as store:
            yield store
    monkeypatch.setattr(router_module, "palace_store", palace)
    monkeypatch.setattr(router_module, "market_store", market)
    monkeypatch.setattr("src.review.build_winrate_summary", lambda *a, **kw: [{"tenant": active[0]}])
    router_module.clear_review_cache()
    app = FastAPI()
    app.include_router(router_module.build_review_router())
    try:
        with TestClient(app) as client:
            assert client.get("/api/winrate/summary").json() == [{"tenant": "a"}]
            active[0] = "b"
            assert client.get("/api/winrate/summary").json() == [{"tenant": "b"}]
            active[0] = "a"
            assert client.get("/api/winrate/summary").json() == [{"tenant": "a"}]
    finally:
        router_module.clear_review_cache()
