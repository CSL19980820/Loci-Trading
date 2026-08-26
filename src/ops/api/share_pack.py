"""一键分享打包 HTTP。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from src.ops.application.share_pack import (
    SharePackError,
    build_share_pack,
    share_pack_status,
)
from src.shared.version import APP_RELEASED_AT, APP_RELEASE_SUMMARY, APP_VERSION


class SharePackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include: list[str] = Field(default_factory=list)
    password: str = Field(min_length=1)


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def build_share_pack_router(*, write_dependency) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    @router.get("/api/ops/version", tags=["ops"])
    def get_app_version() -> dict[str, Any]:
        """产品版本（与前端 release.ts 对齐）。"""
        return {
            "version": APP_VERSION,
            "released_at": APP_RELEASED_AT,
            "summary": APP_RELEASE_SUMMARY,
        }

    @router.get("/api/ops/share-pack/status", tags=["ops"])
    def get_share_pack_status() -> dict[str, Any]:
        """是否可打包、可选件体积（不含解压密码）。"""
        return share_pack_status()

    @router.post("/api/ops/share-pack", tags=["ops"])
    def post_share_pack(
        payload: SharePackRequest,
        _write: None = write_guard,
    ) -> FileResponse:
        """生成加密 zip 并作为附件下载。仅编译产物可打包。"""
        try:
            result = build_share_pack(
                include=payload.include,
                password=payload.password,
            )
        except SharePackError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"打包失败：{exc}") from exc

        path = Path(result["path"])
        notes = result.get("sanitize_notes") or []
        return FileResponse(
            path,
            media_type="application/zip",
            filename=str(result["filename"]),
            # 正文是二进制附件，脱敏回执只能走 header；值保持 ASCII
            headers={
                "X-Loci-Sanitized": "1" if result.get("sanitized") else "0",
                "X-Loci-Sanitize-Count": str(len(notes)),
                "Access-Control-Expose-Headers": "X-Loci-Sanitized, X-Loci-Sanitize-Count",
            },
            background=BackgroundTask(_unlink_quiet, path),
        )

    return router
