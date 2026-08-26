"""统一通知分发：安静时段 + 企微 + Bark。

正文须由调用方用确定性模板拼好；本模块只负责出站。
"""
from __future__ import annotations

import logging
from typing import Any

from src.ops.application.notify_bark import BarkError, send_bark_text
from src.ops.application.notify_policy import load_notify_policy
from src.ops.application.notify import NotifyError, send_wecom_text

logger = logging.getLogger(__name__)


def load_notify_channels(store: object) -> list[dict[str, Any]]:
    getter = getattr(store, "get_setting", None)
    if not callable(getter):
        return []
    raw = getter("notify_channels", []) or []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def save_notify_channels(store: object, channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in channels:
        if not isinstance(item, dict):
            continue
        ctype = str(item.get("type") or "").strip().lower()
        if ctype not in {"wecom", "bark"}:
            continue
        cleaned.append(
            {
                "id": str(item.get("id") or ctype),
                "type": ctype,
                "enabled": bool(item.get("enabled", True)),
                "is_default": bool(item.get("is_default", ctype == "wecom")),
                "config": item.get("config") if isinstance(item.get("config"), dict) else {},
            }
        )
    setter = getattr(store, "set_setting", None)
    if callable(setter):
        setter("notify_channels", cleaned)
    return cleaned


def _resolve_channels(
    store: object,
    *,
    channel_ids: list[str] | None,
) -> list[dict[str, Any]]:
    channels = load_notify_channels(store)
    # 兼容：无 channels 表时回退 wecom_webhook
    if not channels:
        getter = getattr(store, "get_setting", None)
        url = ""
        if callable(getter):
            raw = getter("wecom_webhook", {}) or {}
            if isinstance(raw, dict):
                url = str(raw.get("url") or "").strip()
        if url:
            channels = [
                {
                    "id": "wecom",
                    "type": "wecom",
                    "enabled": True,
                    "is_default": True,
                    "config": {"url": url},
                }
            ]
    enabled = [c for c in channels if c.get("enabled")]
    if channel_ids:
        wanted = {str(x) for x in channel_ids}
        picked = [c for c in enabled if str(c.get("id")) in wanted]
        return picked
    defaults = [c for c in enabled if c.get("is_default")]
    return defaults or enabled


def dispatch_text(
    store: object,
    *,
    title: str,
    body: str,
    channel_ids: list[str] | None = None,
    bypass_quiet: bool = False,
    webhook_override: str = "",
    prepend_title_to_wecom: bool = True,
) -> dict[str, Any]:
    """向默认或指定渠道发送 text。"""
    policy = load_notify_policy(store)
    if not bypass_quiet and policy.is_quiet_now():
        return {"success": False, "skipped": "quiet_hours", "sent": []}

    channels = _resolve_channels(store, channel_ids=channel_ids)
    if webhook_override.strip():
        channels = [
            {
                "id": "wecom",
                "type": "wecom",
                "enabled": True,
                "is_default": True,
                "config": {"url": webhook_override.strip()},
            }
        ]
    if not channels:
        return {
            "success": False,
            "error": "没有可用的通知渠道（Webhook 未配置）",
            "sent": [],
        }

    sent: list[str] = []
    errors: list[str] = []
    for channel in channels:
        ctype = str(channel.get("type") or "")
        config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
        try:
            if ctype == "wecom":
                url = str(config.get("url") or "").strip()
                if not url:
                    getter = getattr(store, "get_setting", None)
                    if callable(getter):
                        raw = getter("wecom_webhook", {}) or {}
                        if isinstance(raw, dict):
                            url = str(raw.get("url") or "").strip()
                if not url:
                    raise NotifyError("企微 Webhook 未配置")
                # 企微无独立 title 字段；已自带标题的业务正文可显式关闭重复前缀。
                content = (
                    body
                    if not title or not prepend_title_to_wecom
                    else f"【{title}】\n{body}"
                )
                send_wecom_text(url, content)
                sent.append("wecom")
            elif ctype == "bark":
                send_bark_text(
                    device_key=str(config.get("device_key") or ""),
                    title=title or "Loci",
                    body=body,
                    server_url=str(config.get("server_url") or ""),
                )
                sent.append("bark")
            else:
                errors.append(f"未知渠道: {ctype}")
        except (NotifyError, BarkError) as exc:
            errors.append(str(exc))
            logger.warning("notify channel %s failed: %s", ctype, exc)
        except Exception as exc:  # noqa: BLE001 — 出站失败不拖垮任务
            errors.append(str(exc))
            logger.warning("notify channel %s failed: %s", ctype, exc)

    return {
        "success": bool(sent) and not errors,
        "partial": bool(sent) and bool(errors),
        "sent": sent,
        "errors": errors,
    }
