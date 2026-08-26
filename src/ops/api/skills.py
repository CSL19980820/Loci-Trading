"""Skill 包与对话式 Skill Run HTTP。"""
from __future__ import annotations

from pathlib import Path
import logging
import tempfile
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from src.ops.api.schemas import (
    SkillGenerateRequest,
    SkillJobConfig,
    SkillRunCreate,
    SkillRunReply,
    SkillStrategyConfig,
)
from src.shared.api_deps import MAX_UPLOAD_BYTES, missing_dependency, ops_store

logger = logging.getLogger(__name__)


def build_skills_router(
    *,
    write_dependency,
    market_db: str | None = None,
    ops_db: str | None = None,
    palace_db: str | None = None,
    scheduler_getter=None,
) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _ops():
        return ops_store(ops_db)

    def _reload_scheduler() -> None:
        if scheduler_getter is None:
            return
        scheduler = scheduler_getter()
        if scheduler is not None and scheduler.running:
            try:
                scheduler.reload()
            except Exception:
                logger.exception("reload scheduler after skill job change failed")

    @router.get("/api/skills", tags=["skills"])
    def list_skills() -> list[dict[str, Any]]:
        """扫描 data/skills/*/SKILL.md（不写 ops.db）。"""
        try:
            from src.ops.application.skills import discover_skills
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        return [
            {k: v for k, v in pkg.to_record().items() if k != "instructions"}
            for pkg in discover_skills()
            if str(pkg.metadata.get("capability") or "").strip().lower() != "screen"
        ]

    @router.get("/api/skills/{slug}", tags=["skills"])
    def get_skill(slug: str) -> dict[str, Any]:
        try:
            from src.ops.application.skills import resolve_skill
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        skill = resolve_skill(slug)
        if skill is None or str((skill.get("metadata") or {}).get("capability") or "").strip().lower() == "screen":
            raise HTTPException(
                status_code=404,
                detail=f"未找到技能：{slug}（请复制到 data/skills/{slug}/SKILL.md）",
            )
        return skill

    @router.post("/api/skills/rescan", tags=["skills"])
    def rescan_skills(_write: None = write_guard) -> dict[str, Any]:
        """重新扫描 data/skills（只读磁盘，不写库）。"""
        try:
            from src.ops.application.skills import discover_skills
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        packages = discover_skills()
        agent_skills = [
            pkg for pkg in packages
            if str(pkg.metadata.get("capability") or "").strip().lower() != "screen"
        ]
        return {"count": len(agent_skills), "slugs": [pkg.slug for pkg in agent_skills]}

    @router.post("/api/skills/sync-templates", tags=["skills"])
    def sync_skill_templates(
        overwrite: bool = Query(default=True),
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """把仓库 templates/skills 下的战法模板安装到 data/skills。"""
        try:
            from src.ops.application.skills import SkillError, sync_skills_from_templates
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        try:
            return sync_skills_from_templates(overwrite=overwrite)
        except SkillError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/skills", tags=["skills"], status_code=201)
    def install_skill_api(
        file: UploadFile = File(...), _write: None = write_guard
    ) -> dict[str, Any]:
        """上传并安装技能包 zip 到 data/skills/。"""
        try:
            from src.ops import install_skill
            from src.ops.application.screen import ScreenPackageError, read_screen_archive
            from src.ops.application.screen.storage import archive_declares_screen_capability
            from src.ops.application.skills import SkillError
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        if not (file.filename or "").lower().endswith(".zip"):
            raise HTTPException(status_code=422, detail="技能包必须是 .zip 文件")

        with tempfile.TemporaryDirectory(prefix="skill-upload-") as tmp:
            target = Path(tmp) / "package.zip"
            written = 0
            with open(target, "wb") as handle:
                while chunk := file.file.read(1024 * 256):
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"技能包超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限",
                        )
                    handle.write(chunk)
            try:
                read_screen_archive(target)
            except ScreenPackageError as exc:
                if archive_declares_screen_capability(target):
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
            else:
                raise HTTPException(
                    status_code=422,
                    detail="capability=screen 的包请走 /api/screen-skills/import",
                )
            try:
                package = install_skill(target)
            except SkillError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        record = package.to_record()
        return {key: value for key, value in record.items() if key != "instructions"}

    @router.delete("/api/skills/{slug}", tags=["skills"])
    def remove_skill(slug: str, _write: None = write_guard) -> dict[str, bool]:
        try:
            from src.ops import resolve_skill, uninstall_skill
            from src.ops.application.skills import SkillError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        skill = resolve_skill(slug)
        if skill is not None and str((skill.get("metadata") or {}).get("capability") or "").strip().lower() == "screen":
            raise HTTPException(status_code=404, detail=f"未安装的技能：{slug}")
        try:
            removed_fs = uninstall_skill(slug)
        except SkillError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not removed_fs:
            raise HTTPException(status_code=404, detail=f"未安装的技能：{slug}")
        return {"removed": True}

    from src.ops.api.skill_runs_api import register_skill_run_routes
    from src.ops.api.skill_jobs_api import register_skill_job_routes

    register_skill_run_routes(
        router,
        write_guard=write_guard,
        ops_factory=_ops,
        market_db=market_db,
        ops_db=ops_db,
        palace_db=palace_db,
    )
    register_skill_job_routes(
        router,
        write_guard=write_guard,
        ops_factory=_ops,
        reload_scheduler=_reload_scheduler,
    )

    @router.post("/api/skills/generate", tags=["skills"])
    def generate_skill_md(
        payload: SkillGenerateRequest, _write: None = write_guard
    ) -> dict[str, Any]:
        """根据描述让 AI 生成 SKILL.md 内容。

        返回生成的文本，用户可以复制或直接下载为 .zip 安装包。
        此接口不自动安装，安装走 POST /api/skills（上传 zip）。
        """
        try:
            from src.ai import resolve_config
            from src.strategy.application.converter import build_skill_prompt
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        with _ops() as store:
            try:
                provider = resolve_config(
                    store, payload.provider,
                    model=payload.model,
                )
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"供应商配置错误：{exc}") from exc

        prompt = build_skill_prompt(
            description=payload.description,
            slug=payload.slug,
            name=payload.name,
            context_hints=payload.context_hints,
        )
        try:
            from src.ai import ChatMessage, chat
            messages = [ChatMessage(role="user", content=prompt)]
            response = chat(
                provider,
                messages,
                max_tokens=2048,
                temperature=0.3,
                thinking=payload.thinking,
            )
            skill_md = response.text.strip()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM 请求失败：{exc}") from exc

        return {
            "slug": payload.slug,
            "name": payload.name,
            "skill_md": skill_md,
        }


    return router
