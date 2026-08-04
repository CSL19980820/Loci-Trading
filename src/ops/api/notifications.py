"""企微通知设置 HTTP。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.app.legacy.quant_common import (
    WecomScreenTemplateModel,
    WecomSettingsUpdate,
    ops_store,
)


def build_notification_settings_router(
    *,
    write_dependency,
    ops_db: str | None = None,
) -> APIRouter:
    """构造企微通知设置路由。"""
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _ops():
        return ops_store(ops_db)

    @router.get("/api/ops/settings/wecom", tags=["notify"])
    def get_wecom_settings() -> dict[str, Any]:
        from src.ops.application.notify import (
            load_screen_template,
            mask_wecom_webhook,
            preview_screen_template,
        )

        with _ops() as store:
            raw = store.get_setting("wecom_webhook", {}) or {}
            url = str(raw.get("url") or "")
            screen_template = load_screen_template(store)
        return {
            "configured": bool(url),
            "url_masked": mask_wecom_webhook(url) if url else "",
            "screen_template": screen_template,
            "preview": preview_screen_template(screen_template, kind="quant"),
        }

    @router.put("/api/ops/settings/wecom", tags=["notify"])
    def put_wecom_settings(
        payload: WecomSettingsUpdate, _write: None = write_guard
    ) -> dict[str, Any]:
        from src.ops.application.notify import (
            NotifyError,
            load_screen_template,
            mask_wecom_webhook,
            normalize_screen_template,
            preview_screen_template,
            validate_wecom_webhook,
        )

        if payload.url is None and payload.screen_template is None:
            raise HTTPException(status_code=422, detail="没有要更新的字段")

        with _ops() as store:
            if payload.url is not None:
                url = payload.url.strip()
                if not url:
                    store.delete_setting("wecom_webhook")
                else:
                    try:
                        validated = validate_wecom_webhook(url)
                    except NotifyError as exc:
                        raise HTTPException(status_code=422, detail=str(exc)) from exc
                    store.set_setting("wecom_webhook", {"url": validated})
            if payload.screen_template is not None:
                normalized = normalize_screen_template(payload.screen_template.model_dump())
                store.set_setting("wecom_screen_template", normalized)

            raw = store.get_setting("wecom_webhook", {}) or {}
            url = str(raw.get("url") or "")
            screen_template = load_screen_template(store)
        return {
            "configured": bool(url),
            "url_masked": mask_wecom_webhook(url) if url else "",
            "screen_template": screen_template,
            "preview": preview_screen_template(screen_template, kind="quant"),
        }

    @router.post("/api/ops/settings/wecom/test", tags=["notify"])
    def test_wecom_settings(_write: None = write_guard) -> dict[str, Any]:
        from src.ops.application.notify import NotifyError, send_wecom_text

        with _ops() as store:
            raw = store.get_setting("wecom_webhook", {}) or {}
            url = str(raw.get("url") or "")
        if not url:
            raise HTTPException(status_code=422, detail="尚未配置企业微信 Webhook")
        try:
            send_wecom_text(
                url,
                "【记忆宫殿连通测试】\n企微推送已接通（text）。可在运维配置触价/选股/日终简报任务。",
            )
        except NotifyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"ok": True}

    @router.post("/api/ops/settings/wecom/preview", tags=["notify"])
    def preview_wecom_screen_template(
        payload: WecomScreenTemplateModel,
    ) -> dict[str, Any]:
        """选股模板即时预览（不落库）。"""
        from src.ops.application.notify import (
            normalize_screen_template,
            preview_screen_template,
        )

        template = normalize_screen_template(payload.model_dump())
        return {
            "screen_template": template,
            "preview": preview_screen_template(template, kind="quant"),
            "preview_skills": preview_screen_template(template, kind="skills"),
        }

    return router
