"""企微通知设置 HTTP。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.ops.api.schemas import WecomScreenTemplateModel, WecomSettingsUpdate
from src.shared.api_deps import ops_store


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

    @router.get("/api/ops/settings/notify", tags=["notify"])
    def get_notify_settings() -> dict[str, Any]:
        from src.ops.application.notify_dispatch import load_notify_channels
        from src.ops.application.notify_policy import load_notify_policy

        with _ops() as store:
            policy = load_notify_policy(store)
            channels = load_notify_channels(store)
            bark = next((c for c in channels if c.get("type") == "bark"), None)
        return {
            "quiet_hours": policy.quiet_hours,
            "timezone": policy.timezone,
            "bark": {
                "enabled": bool(bark and bark.get("enabled")),
                "device_key": (bark or {}).get("config", {}).get("device_key", "") if bark else "",
                "server_url": (bark or {}).get("config", {}).get("server_url", "") if bark else "",
            },
            "channels": [
                {
                    "id": c.get("id"),
                    "type": c.get("type"),
                    "enabled": c.get("enabled"),
                    "is_default": c.get("is_default"),
                }
                for c in channels
            ],
        }

    @router.put("/api/ops/settings/notify", tags=["notify"])
    def put_notify_settings(payload: dict[str, Any], _write: None = write_guard) -> dict[str, Any]:
        from src.ops.application.notify_dispatch import load_notify_channels, save_notify_channels
        from src.ops.application.notify_policy import save_notify_policy
        from src.ops.infrastructure.store import OpsError

        quiet = str(payload.get("quiet_hours") or "")
        timezone = str(payload.get("timezone") or "Asia/Shanghai")
        bark = payload.get("bark") if isinstance(payload.get("bark"), dict) else {}
        try:
            with _ops() as store:
                save_notify_policy(store, quiet_hours=quiet, timezone=timezone)
                channels = [c for c in load_notify_channels(store) if c.get("type") != "bark"]
                if bark.get("device_key") or bark.get("enabled"):
                    channels.append(
                        {
                            "id": "bark",
                            "type": "bark",
                            "enabled": bool(bark.get("enabled", True)),
                            "is_default": bool(bark.get("is_default", False)),
                            "config": {
                                "device_key": str(bark.get("device_key") or ""),
                                "server_url": str(bark.get("server_url") or ""),
                            },
                        }
                    )
                # 确保 wecom 渠道条目存在（若已有 webhook）
                raw = store.get_setting("wecom_webhook", {}) or {}
                url = str(raw.get("url") or "") if isinstance(raw, dict) else ""
                if url and not any(c.get("type") == "wecom" for c in channels):
                    channels.insert(
                        0,
                        {
                            "id": "wecom",
                            "type": "wecom",
                            "enabled": True,
                            "is_default": True,
                            "config": {"url": url},
                        },
                    )
                save_notify_channels(store, channels)
        except OpsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return get_notify_settings()

    @router.post("/api/ops/settings/notify/test", tags=["notify"])
    def test_notify_settings(_write: None = write_guard) -> dict[str, Any]:
        from src.ops.application.notify_dispatch import dispatch_text

        with _ops() as store:
            outcome = dispatch_text(
                store,
                title="Loci 连通测试",
                body="通知分发已接通（可含企微/Bark）。安静时段测试会 bypass。",
                bypass_quiet=True,
            )
        if not outcome.get("sent"):
            raise HTTPException(
                status_code=422,
                detail=outcome.get("error") or "; ".join(outcome.get("errors") or ["推送失败"]),
            )
        return {"ok": True, "notify": outcome}

    return router
