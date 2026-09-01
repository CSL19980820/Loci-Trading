"""战法监测 HTTP：调参启停、角色留痕、实时预览。

与 `skills.py`（技能包安装 / Skill Run / 定时绑定）分开：这里只服务
「盯盘扫描链」这一件事，且都要求目标技能是专属战法包。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.ops.api.schemas import WatchTuningIn
from src.shared.api_deps import missing_dependency, ops_store


def build_skill_watch_router(*, write_dependency, ops_db: str | None = None) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _ops():
        return ops_store(ops_db)

    def _require_strategy_skill(slug: str) -> dict[str, Any]:
        try:
            from src.ops.application.skill_strategy_config import is_strategy_skill
            from src.ops.application.skills import resolve_skill
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        skill = resolve_skill(slug)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"未找到技能：{slug}")
        if not is_strategy_skill(skill):
            raise HTTPException(status_code=422, detail=f"技能 {slug} 不是专属战法包")
        return skill

    @router.get("/api/skills/{slug}/watch-tuning", tags=["skills"])
    def get_watch_tuning(slug: str) -> dict[str, Any]:
        """战法监测调参：每段流水线的启停 + 各档阈值。未存过给默认档。

        ``schema`` 描述字段清单（中文名/步长/值域），前端照着渲染，
        避免后端加了阈值而界面漏掉。
        """
        from src.ops.application.skill_watch.tuning import (
            default_tuning,
            load_tuning,
            list_presets,
            tuning_schema,
        )

        _require_strategy_skill(slug)
        with _ops() as store:
            return {
                "slug": slug,
                "tuning": load_tuning(store, slug),
                "defaults": default_tuning(),
                "schema": tuning_schema(),
                "presets": list_presets(),
            }

    @router.put("/api/skills/{slug}/watch-tuning", tags=["skills"])
    def put_watch_tuning(
        slug: str, payload: WatchTuningIn, _write: None = write_guard
    ) -> dict[str, Any]:
        """按段合并保存；传 ``preset`` 时整档套用命名预设。未知键丢弃、越界值钳到边界。"""
        from src.ops.application.skill_watch.tuning import (
            apply_preset,
            default_tuning,
            list_presets,
            save_tuning,
            tuning_schema,
        )

        _require_strategy_skill(slug)
        with _ops() as store:
            if payload.preset:
                saved = apply_preset(store, slug, payload.preset)
            else:
                saved = save_tuning(store, slug, payload.model_dump(exclude_none=True))
        return {
            "slug": slug,
            "tuning": saved,
            "defaults": default_tuning(),
            "schema": tuning_schema(),
            "presets": list_presets(),
        }

    @router.delete("/api/skills/{slug}/watch-tuning", tags=["skills"])
    def reset_watch_tuning(slug: str, _write: None = write_guard) -> dict[str, Any]:
        from src.ops.application.skill_watch.tuning import (
            default_tuning,
            list_presets,
            reset_tuning,
            tuning_schema,
        )

        _require_strategy_skill(slug)
        with _ops() as store:
            restored = reset_tuning(store, slug)
        return {
            "slug": slug,
            "tuning": restored,
            "defaults": default_tuning(),
            "schema": tuning_schema(),
            "presets": list_presets(),
        }

    @router.get("/api/skills/{slug}/leader-roles", tags=["skills"])
    def get_leader_roles(
        slug: str,
        code: str = "",
        trade_date: str = "",
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        """龙头角色留痕、角色变化与演进摘要。只追加的观测流，可整表清空重建。"""
        from src.ops.application.skill_watch.role_stats import (
            role_transitions,
            suggest_tuning_adjustments,
            summarize_role_history,
        )
        from src.ops.application.skill_watch.tuning import load_tuning

        _require_strategy_skill(slug)
        with _ops() as store:
            history = store.list_leader_roles(
                slug, code=code, trade_date=trade_date, limit=limit
            )
            # 摘要要覆盖足够长的窗口，不能只看当前这一页
            full = history if (code or trade_date) else store.list_leader_roles(slug, limit=2000)
            current = load_tuning(store, slug)
            return {
                "slug": slug,
                "history": history,
                "transitions": role_transitions(full, limit=30),
                "summary": summarize_role_history(full),
                "suggestions": suggest_tuning_adjustments(full, current_tuning=current),
            }

    @router.post("/api/skills/{slug}/watch-preview", tags=["skills"])
    def preview_skill_watch(slug: str, _write: None = write_guard) -> dict[str, Any]:
        """按当前实时数据试跑一次战法监测，只读不落库。

        与定时监测同一套确定性扫描，但不写纸面舱、不推送、不调 LLM；
        悟道未装配时直接返回不可用，不消耗配额。
        `persist=False` 是「不落库」的真正兑现处，别去掉。
        """
        try:
            from src.ops.application.jobs import JobError
            from src.ops.application.skill_watch import run_skill_watch
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        _require_strategy_skill(slug)
        try:
            with _ops() as store:
                return run_skill_watch(
                    {"skill": slug, "watch_use_ai": False}, store=store, persist=False
                )
        except JobError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
