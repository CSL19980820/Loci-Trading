from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.ops import OpsStore
from src.ops.application.screen import ScreenPackageError
from src.strategy.api.version_router import build_strategy_version_router
from src.strategy.application.catalog import describe_all, replace_screen_engines
from src.strategy.application.screen_formula import build_formula_engine


class _CustomEngine:
    slug = "metadata-screen"
    name = "元数据测试战法"
    description = "仅用于版本路由测试"
    entry_timing = "next_open"
    source_kind = "formula"
    version = "screen-revision-a"
    strategy_revision = "screen-revision-a"

    def default_params(self) -> dict:
        return {}

    def required_fields(self) -> tuple[str, ...]:
        return ("close",)

    def min_bars(self) -> int:
        return 1


class _Market:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_catalog_uses_screen_package_metadata_without_mutating_engine() -> None:
    engine = build_formula_engine({
        "slug": "metadata-screen",
        "name": "元数据测试战法",
        "description": "仅用于目录测试",
        "formula": "PICK: CLOSE>MA(CLOSE,2);\n",
        "manifest": {
            "schema_version": 1,
            "entry_timing": "next_open",
            "min_bars": 2,
            "params": {},
            "output": {"signal": "PICK"},
            "factors": [],
        },
    })
    assert engine.version_history == []
    replace_screen_engines(
        [engine],
        metadata_by_slug={
            "metadata-screen": {
                "version": "a" * 64,
                "version_history": [{"version": "b" * 64}],
            }
        },
    )
    try:
        item = next(item for item in describe_all() if item["slug"] == "metadata-screen")
        assert item["version"] == "a" * 64
        assert item["version_history"] == [{"version": "b" * 64}]
    finally:
        replace_screen_engines([])


def test_strategy_catalog_persists_and_reads_builtin_entry_instructions(tmp_path: Path) -> None:
    ops_db = tmp_path / "ops.db"
    with OpsStore(ops_db) as store:
        store.upsert_strategy_doc(
            "rsi30-dip",
            entry_instructions="人工维护的 RSI 买入说明",
        )

    app = FastAPI()
    app.include_router(build_strategy_version_router(
        write_dependency=lambda: None, market_db=None, ops_db=str(ops_db)
    ))
    with TestClient(app) as client:
        response = client.get("/api/strategies")

    assert response.status_code == 200, response.text
    described = {item["slug"]: item for item in response.json()}
    assert described["rsi30-dip"]["entry_instructions"] == "人工维护的 RSI 买入说明"
    assert "T+2 收盘卖出" in described["sanyuan-tail-v1"]["entry_instructions"]
    with OpsStore(ops_db) as store:
        assert store.get_strategy_doc("sanyuan-tail-v1")["entry_instructions"]


def test_formula_version_routes_support_frontend_rollback_contract() -> None:
    current_revision = "b" * 64
    archived_revision = "a" * 64
    engine = build_formula_engine({
        "slug": "metadata-screen",
        "name": "元数据测试战法",
        "description": "仅用于版本路由测试",
        "formula": "PICK: CLOSE>MA(CLOSE,2);\n",
        "manifest": {
            "schema_version": 1,
            "entry_timing": "next_open",
            "min_bars": 2,
            "params": {},
            "output": {"signal": "PICK"},
            "factors": [],
        },
    })
    history = [{"version": archived_revision, "package_revision": archived_revision}]
    app = FastAPI()
    app.include_router(build_strategy_version_router(
        write_dependency=lambda: None, market_db=None, ops_db=None
    ))
    replace_screen_engines(
        [engine],
        metadata_by_slug={
            "metadata-screen": {"version": current_revision, "version_history": history}
        },
    )
    try:
        with (
            TestClient(app) as client,
            patch("src.app.screen_skills.list_screen_skill_history", return_value=history),
            patch("src.app.screen_skills.get_screen_skill_item", return_value={
                "package_revision": current_revision
            }),
            patch("src.app.screen_skills.rollback_screen_skill") as rollback,
        ):
            listed = client.get("/api/strategies/metadata-screen/versions")
            response = client.post(
                "/api/strategies/metadata-screen/rollback",
                json={"version": archived_revision},
            )
        assert listed.status_code == 200, listed.text
        assert listed.json() == history
        assert response.status_code == 200, response.text
        assert response.json()["version"] == current_revision
        rollback.assert_called_once_with(
            "metadata-screen", archived_revision, expected_revision=current_revision
        )
    finally:
        replace_screen_engines([])


def test_formula_rollback_rejects_anonymous_callers_before_package_access() -> None:
    def reject_write() -> None:
        raise HTTPException(status_code=401, detail="write access denied")

    app = FastAPI()
    app.include_router(build_strategy_version_router(
        write_dependency=reject_write, market_db=None, ops_db=None
    ))
    with (
        TestClient(app, raise_server_exceptions=False) as client,
        patch("src.app.screen_skills.get_screen_skill_item", side_effect=AssertionError("must not load")),
    ):
        response = client.post(
            "/api/strategies/metadata-screen/rollback",
            json={"version": "a" * 64},
        )
    assert response.status_code == 401


def test_formula_rollback_reports_missing_archive_as_not_found() -> None:
    current_revision = "b" * 64
    engine = build_formula_engine({
        "slug": "metadata-screen",
        "name": "元数据测试战法",
        "description": "仅用于版本路由测试",
        "formula": "PICK: CLOSE>MA(CLOSE,2);\n",
        "manifest": {
            "schema_version": 1,
            "entry_timing": "next_open",
            "min_bars": 2,
            "params": {},
            "output": {"signal": "PICK"},
            "factors": [],
        },
    })
    app = FastAPI()
    app.include_router(build_strategy_version_router(
        write_dependency=lambda: None, market_db=None, ops_db=None
    ))
    replace_screen_engines([engine])
    try:
        with (
            TestClient(app, raise_server_exceptions=False) as client,
            patch("src.app.screen_skills.get_screen_skill_item", return_value={
                "package_revision": current_revision
            }),
            patch(
                "src.app.screen_skills.rollback_screen_skill",
                side_effect=ScreenPackageError("history_not_found"),
            ),
        ):
            response = client.post(
                "/api/strategies/metadata-screen/rollback",
                json={"version": "a" * 64},
            )
        assert response.status_code == 404
        assert response.json()["detail"] == "history_not_found"
    finally:
        replace_screen_engines([])


def test_trade_backtest_persists_only_custom_strategy_metadata(tmp_path: Path) -> None:
    ops_db = tmp_path / "ops.db"
    market_db = tmp_path / "market.db"
    app = FastAPI()
    app.include_router(build_strategy_version_router(
        write_dependency=lambda: None, market_db=str(market_db), ops_db=str(ops_db)
    ))
    trade = SimpleNamespace(
        strategy_slug="metadata-screen",
        config={"hold_days": 3},
        metrics={"trades": 4, "win_rate": 50.0, "avg_net_return": 1.1, "profit_factor": 1.2},
        skipped={},
        trades=[],
    )
    replace_screen_engines([_CustomEngine()])
    try:
        with (
            TestClient(app) as client,
            patch("src.market.MarketStore", return_value=_Market()),
            patch("src.backtest.backtest_strategy", return_value=trade),
        ):
            response = client.post("/api/backtest", json={"strategy": "metadata-screen"})
        assert response.status_code == 200, response.text
        assert response.json()["backtest_metadata"]["version"] == "screen-revision-a"
        assert not market_db.exists()
        with OpsStore(ops_db) as store:
            saved = store.get_strategy_backtest("metadata-screen", "screen-revision-a")
        assert saved is not None
        assert saved["metrics"]["profit_factor"] == 1.2
    finally:
        replace_screen_engines([])


def test_trade_backtest_does_not_overwrite_builtin_metadata(tmp_path: Path) -> None:
    ops_db = tmp_path / "ops.db"
    app = FastAPI()
    app.include_router(build_strategy_version_router(
        write_dependency=lambda: None, market_db=None, ops_db=str(ops_db)
    ))
    trade = SimpleNamespace(
        strategy_slug="rsi30-dip",
        config={"hold_days": 3},
        metrics={"trades": 4, "win_rate": 50.0, "avg_net_return": 1.1, "profit_factor": 1.2},
        skipped={},
        trades=[],
    )
    with (
        TestClient(app) as client,
        patch("src.strategy.api.version_router.market_store", return_value=_Market()),
        patch("src.backtest.backtest_strategy", return_value=trade),
    ):
        response = client.post("/api/backtest", json={"strategy": "rsi30-dip"})
    assert response.status_code == 200, response.text
    assert "backtest_metadata" not in response.json()
    assert not ops_db.exists()


def test_backtest_write_guard_runs_before_market_access() -> None:
    def reject_write() -> None:
        raise HTTPException(status_code=401, detail="write access denied")

    app = FastAPI()
    app.include_router(build_strategy_version_router(
        write_dependency=reject_write, market_db=None, ops_db=None
    ))
    with (
        TestClient(app, raise_server_exceptions=False) as client,
        patch("src.market.MarketStore", side_effect=AssertionError("market must not open")),
    ):
        response = client.post("/api/backtest", json={"strategy": "qianlong-close-v3"})
    assert response.status_code == 401
