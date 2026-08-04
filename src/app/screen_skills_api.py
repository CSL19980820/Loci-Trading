"""Screen Skill HTTP。"""
from __future__ import annotations

from pathlib import Path
import logging
import tempfile
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from src.app.legacy.quant_common import MAX_UPLOAD_BYTES, missing_dependency
from src.app.screen_skill_models import (
    ScreenSkillDeleteRequest,
    ScreenSkillDraftModel,
    ScreenSkillGenerateRequest,
    ScreenSkillPreviewRequest,
    ScreenSkillUpdateRequest,
)


logger = logging.getLogger(__name__)


def build_screen_skills_router(
    *,
    write_dependency,
    market_db: str | None = None,
    ops_db: str | None = None,
    scheduler_getter=None,
) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _svc():
        from src.app import screen_skills

        return screen_skills

    def _reload_scheduler() -> None:
        if scheduler_getter is None:
            return
        scheduler = scheduler_getter()
        if scheduler is not None and scheduler.running:
            scheduler.reload()

    def _resync_screen_jobs(*, deleted_slug: str | None = None) -> None:
        """战法增删改后同步托管盘后任务并重载调度器。

        不 ensure：新建战法的 ``screen:{slug}`` 任务行要到下次列表接口才创建，
        进程内调度器不 reload，当天 15:30 盘后选股不会触发。
        不删任务：删除战法的残留 job 会每天到点执行并落失败记录。
        """
        from src.app.legacy.quant_common import ops_store

        try:
            with ops_store(ops_db) as store:
                if deleted_slug:
                    stale = store.get_job_by_name(f"screen:{deleted_slug}")
                    if stale is not None:
                        store.delete_job(stale["id"])
                store.ensure_managed_screen_jobs()
        except Exception:  # noqa: BLE001 — 任务同步失败不挡战法保存成功
            logger.exception("战法变更后同步盘后任务失败（slug=%s）", deleted_slug)
        _reload_scheduler()

    @router.get("/api/screen-skills", tags=["strategy"])
    def list_screen_skills() -> list[dict[str, Any]]:
        try:
            return _svc().list_screen_skill_items()
        except ImportError as exc:
            raise missing_dependency(exc) from exc

    @router.get("/api/screen-skills/catalog", tags=["strategy"])
    def get_screen_skill_catalog() -> dict[str, Any]:
        try:
            return _svc().get_screen_skill_catalog()
        except ImportError as exc:
            raise missing_dependency(exc) from exc

    @router.get("/api/screen-skills/{slug}", tags=["strategy"])
    def get_screen_skill(slug: str) -> dict[str, Any]:
        item = _svc().get_screen_skill_item(slug)
        if item is None:
            raise HTTPException(status_code=404, detail=f"未找到 Screen Skill：{slug}")
        return item

    @router.get("/api/screen-skills/{slug}/history", tags=["strategy"])
    def list_screen_skill_history(slug: str) -> list[dict[str, str]]:
        return _svc().list_screen_skill_history(slug)

    @router.post("/api/screen-skills/{slug}/history/{revision}/rollback", tags=["strategy"])
    def rollback_screen_skill(
        slug: str,
        revision: str,
        expected_revision: str | None = Query(default=None, min_length=1),
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            item = _svc().rollback_screen_skill(
                slug, revision, expected_revision=expected_revision
            )
        except Exception as exc:
            _translate_screen_error(exc)
        _resync_screen_jobs()
        return item

    @router.delete("/api/screen-skills/{slug}/history/{revision}", tags=["strategy"])
    def delete_screen_skill_history(
        slug: str, revision: str, _write: None = write_guard
    ) -> dict[str, bool]:
        try:
            removed = _svc().delete_screen_skill_history(slug, revision)
        except Exception as exc:
            _translate_screen_error(exc)
        if not removed:
            raise HTTPException(status_code=404, detail="history_not_found")
        return {"removed": True}

    @router.post("/api/screen-skills/preview", tags=["strategy"])
    def preview_screen_skill(payload: ScreenSkillPreviewRequest) -> dict[str, Any]:
        try:
            return _svc().preview_screen_skill(payload, market_db=market_db)
        except Exception as exc:
            _translate_screen_error(exc)

    @router.post("/api/screen-skills", tags=["strategy"], status_code=201)
    def create_screen_skill(payload: ScreenSkillDraftModel, _write: None = write_guard) -> dict[str, Any]:
        try:
            item = _svc().create_screen_skill(payload)
        except Exception as exc:
            _translate_screen_error(exc)
        _resync_screen_jobs()
        return item

    @router.put("/api/screen-skills/{slug}", tags=["strategy"])
    def update_screen_skill(
        slug: str,
        payload: ScreenSkillUpdateRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            item = _svc().update_screen_skill(slug, payload, expected_revision=payload.expected_revision)
        except Exception as exc:
            _translate_screen_error(exc)
        _resync_screen_jobs()
        return item

    @router.delete("/api/screen-skills/{slug}", tags=["strategy"])
    def delete_screen_skill(
        slug: str,
        payload: ScreenSkillDeleteRequest,
        _write: None = write_guard,
    ) -> dict[str, bool]:
        try:
            removed = _svc().delete_screen_skill(slug, expected_revision=payload.expected_revision)
        except Exception as exc:
            _translate_screen_error(exc)
        if not removed:
            raise HTTPException(status_code=404, detail=f"未找到 Screen Skill：{slug}")
        _resync_screen_jobs(deleted_slug=slug)
        return {"removed": True}

    @router.post("/api/screen-skills/import", tags=["strategy"], status_code=201)
    def import_screen_skill(
        file: UploadFile = File(...),
        _write: None = write_guard,
    ) -> dict[str, Any]:
        if not (file.filename or "").lower().endswith(".zip"):
            raise HTTPException(status_code=422, detail="Screen Skill 包必须是 .zip 文件")
        with tempfile.TemporaryDirectory(prefix="screen-import-") as tmp:
            path = Path(tmp) / "screen-skill.zip"
            written = 0
            with open(path, "wb") as handle:
                while chunk := file.file.read(1024 * 256):
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="Screen Skill 包超过上传上限")
                    handle.write(chunk)
            try:
                item = _svc().import_screen_skill_archive(path)
            except Exception as exc:
                _translate_screen_error(exc)
        _resync_screen_jobs()
        return item

    @router.post("/api/screen-skills/generate", tags=["strategy"])
    def generate_screen_skill(
        payload: ScreenSkillGenerateRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            return _svc().generate_screen_skill_draft(payload, ops_db=ops_db)
        except Exception as exc:
            _translate_screen_error(exc)

    return router


def _translate_screen_error(exc: Exception) -> None:
    from src.ops.application.screen import ScreenPackageError
    from src.strategy.application.screen_formula import ScreenFormulaError

    if isinstance(exc, ScreenFormulaError):
        detail = {"ok": False, "diagnostics": [item.to_dict() for item in exc.diagnostics]} if exc.diagnostics else {"ok": False, "diagnostics": [exc.to_dict()]}
        raise HTTPException(status_code=422, detail=detail) from exc
    if isinstance(exc, ScreenPackageError):
        detail = str(exc)
        if detail in {"revision_conflict", "slug_conflict", "builtin_slug_conflict"}:
            raise HTTPException(status_code=409, detail=detail) from exc
        if detail in {"not_found", "history_not_found"}:
            raise HTTPException(status_code=404, detail=detail) from exc
        if _is_resource_exhaustion(detail):
            raise HTTPException(status_code=413, detail=detail) from exc
        raise HTTPException(status_code=422, detail=detail) from exc
    raise exc


def _is_resource_exhaustion(detail: str) -> bool:
    return any(
        token in detail
        for token in ("超过上传上限", "条目过多", "体积过大")
    )
