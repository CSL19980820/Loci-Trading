"""策略目录、交易型回测元数据与旧 Python 自定义策略版本 HTTP。"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.app.legacy.quant_common import BacktestRequest, market_store, missing_dependency, ops_store
from src.ops import OpsError

logger = logging.getLogger(__name__)


class StrategyRollbackRequest(BaseModel):
    """前端统一传字符串：Screen Skill 为 SHA，旧自定义策略为整数。"""

    version: str = Field(min_length=1, max_length=64)


def build_strategy_version_router(*, write_dependency, market_db: str | None, ops_db: str | None) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _ops():
        return ops_store(ops_db)

    def _is_screen_skill(slug: str) -> bool:
        try:
            from src.strategy import get
            from src.strategy.domain.base import StrategyError

            return str(get(slug).source_kind) in {"formula", "python"}
        except StrategyError:
            return False

    def _strategy_summary(slug: str) -> dict[str, Any]:
        from src.strategy import describe_all

        for item in describe_all():
            if item["slug"] == slug:
                return item
        raise HTTPException(status_code=404, detail=f"未知战法：{slug}")

    def _rollback_screen_skill(slug: str, revision: str) -> dict[str, Any]:
        from src.app import screen_skills

        current = screen_skills.get_screen_skill_item(slug)
        if current is None:
            raise HTTPException(status_code=404, detail=f"未找到 Screen Skill：{slug}")
        screen_skills.rollback_screen_skill(
            slug,
            revision,
            expected_revision=str(current["package_revision"]),
        )
        return _strategy_summary(slug)

    def _rollback_legacy_strategy(slug: str, version: str) -> dict[str, Any]:
        try:
            numeric_version = int(version)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="旧自定义策略版本必须是整数") from exc
        from src.strategy.application.converter import restore_custom_strategy_version

        restore_custom_strategy_version(slug, numeric_version, ops_db=ops_db)
        return _strategy_summary(slug)

    @router.get("/api/strategies", tags=["strategy"])
    def list_strategies() -> list[dict[str, Any]]:
        try:
            from src.strategy import describe_all
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        strategies = describe_all()
        with _ops() as store:
            store.ensure_strategy_entry_instructions(strategies)
            metadata = store.strategy_catalog_metadata(strategies)
        return describe_all(metadata_by_slug=metadata)

    @router.post("/api/backtest", tags=["strategy"])
    def run_backtest_api(
        payload: BacktestRequest, _write: None = write_guard
    ) -> dict[str, Any]:
        try:
            from src.backtest import BacktestConfig, backtest_strategy, backtest_strategy_horizon
            from src.strategy import describe_all, get as get_strategy
            from src.strategy.domain.base import StrategyError
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        universe = payload.universe.model_dump(exclude_none=True) if payload.universe else None
        with market_store(market_db) as store:
            try:
                if payload.mode == "horizon":
                    result = backtest_strategy_horizon(
                        store,
                        payload.strategy,
                        start=payload.start,
                        end=payload.end,
                        params=payload.params,
                        codes=payload.codes,
                        universe=universe,
                        horizons=payload.horizons or (1, 3),
                    )
                    return result.to_dict(include_events=payload.include_events)
                trade = backtest_strategy(
                    store,
                    payload.strategy,
                    start=payload.start,
                    end=payload.end,
                    params=payload.params,
                    config=BacktestConfig(
                        hold_days=payload.hold_days,
                        stop_loss_pct=payload.stop_loss_pct,
                        take_profit_pct=payload.take_profit_pct,
                        benchmark=payload.benchmark,
                    ),
                    codes=payload.codes,
                    universe=universe,
                )
            except StrategyError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        body: dict[str, Any] = {
            "strategy": trade.strategy_slug,
            "mode": "trade",
            "config": trade.config,
            "metrics": trade.metrics,
            "skipped": trade.skipped,
        }
        if payload.include_trades:
            body["trades"] = [{**row.__dict__, "alpha_pct": row.alpha_pct} for row in trade.trades]

        engine = get_strategy(trade.strategy_slug)
        if str(getattr(engine, "source_kind", "builtin")) == "builtin":
            return body
        version = next(
            item["version"] for item in describe_all() if item["slug"] == trade.strategy_slug
        )
        metrics = {
            key: trade.metrics.get(key)
            for key in ("trades", "win_rate", "avg_net_return", "profit_factor")
        }
        config = {
            **trade.config,
            "mode": "trade",
            "params": payload.params or {},
            "start": payload.start,
            "end": payload.end,
            "codes": payload.codes,
            "universe": universe,
        }
        try:
            with _ops() as store:
                saved = store.upsert_strategy_backtest(
                    trade.strategy_slug, version, metrics=metrics, config=config
                )
        except sqlite3.Error as exc:
            logger.exception("自定义策略回测元数据写入失败（strategy=%s）", trade.strategy_slug)
            raise HTTPException(status_code=503, detail="回测已完成，但元数据写入失败") from exc
        body["backtest_metadata"] = saved
        return body

    @router.get("/api/strategies/{slug}/versions", tags=["strategy"])
    def list_strategy_versions(slug: str) -> list[dict[str, Any]]:
        if _is_screen_skill(slug):
            from src.app.screen_skills import list_screen_skill_history

            return list_screen_skill_history(slug)
        with _ops() as store:
            return store.list_strategy_versions(slug)

    @router.post("/api/strategies/{slug}/rollback", tags=["strategy"])
    def rollback_strategy_version_from_catalog(
        slug: str, payload: StrategyRollbackRequest, _write: None = write_guard
    ) -> dict[str, Any]:
        """兼容策略详情页：按运行时分派到包归档或旧 Python 版本存储。"""
        try:
            if _is_screen_skill(slug):
                return _rollback_screen_skill(slug, payload.version)
            return _rollback_legacy_strategy(slug, payload.version)
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        except (RuntimeError, OpsError) as exc:
            _translate_version_error(exc)

    @router.post("/api/strategies/{slug}/versions/{version}/rollback", tags=["strategy"])
    def rollback_strategy_version(
        slug: str, version: int, _write: None = write_guard
    ) -> dict[str, Any]:
        try:
            if _is_screen_skill(slug):
                return _rollback_screen_skill(slug, str(version))
            return _rollback_legacy_strategy(slug, str(version))
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        except (RuntimeError, OpsError) as exc:
            _translate_version_error(exc)

    @router.delete("/api/strategies/{slug}/versions/{version}", tags=["strategy"])
    def delete_strategy_version(
        slug: str, version: str, _write: None = write_guard
    ) -> dict[str, bool]:
        try:
            if _is_screen_skill(slug):
                from src.app.screen_skills import delete_screen_skill_history

                removed = delete_screen_skill_history(slug, version)
            else:
                try:
                    numeric_version = int(version)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail="旧自定义策略版本必须是整数") from exc
                with _ops() as store:
                    removed = store.delete_strategy_version(slug, numeric_version)
        except OpsError as exc:
            _translate_version_error(exc)
        except RuntimeError as exc:
            _translate_version_error(exc)
        if not removed:
            raise HTTPException(status_code=404, detail=f"策略 {slug} 不存在版本 {version}")
        return {"removed": True}

    return router


def _translate_version_error(exc: Exception) -> None:
    from src.ops import OpsError
    from src.ops.application.screen import ScreenPackageError

    message = str(exc)
    if isinstance(exc, ScreenPackageError):
        if message == "history_not_found":
            raise HTTPException(status_code=404, detail=message) from exc
        if message in {"revision_conflict", "cannot_delete_active_history"}:
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    if not isinstance(exc, OpsError):
        if isinstance(exc, RuntimeError):
            raise HTTPException(status_code=422, detail=message) from exc
        raise exc
    if "不存在版本" in message or message == "history_not_found":
        raise HTTPException(status_code=404, detail=message) from exc
    if "不能删除" in message or message in {"revision_conflict", "cannot_delete_active_history"}:
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=422, detail=message) from exc
