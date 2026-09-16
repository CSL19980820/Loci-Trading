"""统一通知分发：安静时段 + 企微 + Bark + 可插拔多通道。

正文须由调用方用确定性模板拼好；本模块只负责出站。

**这里是全仓唯一的出站汇聚点**：任务完成/失败（`jobs/notify._maybe_push_wecom`）
与价格提醒命中（`alert_rules.scan_alert_rules`）都走 `dispatch_text`。多通道
是在这一层接进去的，所以那两处调用点一行没改就同时拿到了钉钉/飞书/邮件/站内信。

**两条腿都过限流。** 旧腿（企微/Bark）曾经直接 send、从不问限流器：
`run_job` 的失败分支也会推，而失败路径没有 `wecom_push_mark` 那种按日去重，
一个 `*/5 9-14` 的 `alert_scan` 持续失败就是全天 60+ 条企微。限流不是洁癖，
是「告警刷屏 = 告警失效」。手动「测试」按钮传 ``bypass_rate_limit=True``：
连点两次必须两次都真的发，否则用户会以为通道坏了。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from src.ops.application.notify_bark import BarkError, send_bark_text
from src.ops.application.notify_policy import load_notify_policy
from src.ops.application.notify import NotifyError, send_wecom_text

logger = logging.getLogger(__name__)

#: 走注册表的通道。**不含企微**——企微仍由本模块的旧腿发，两边都发会重复出声
#: （注册表的 WecomChannel 最终也是调 send_wecom_text）。
_EXTRA_CHANNELS = ("dingtalk", "feishu", "webhook", "email", "inbox")

#: 旧腿自己发、但同样要过限流的通道类型。
_LEGACY_CHANNELS = ("wecom", "bark")


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


def _wecom_url(store: object) -> str:
    """企微 URL 的唯一解析口：新键 ``notify:wecom`` 优先，旧键 ``wecom_webhook`` 兜底。

    旧键回退**不许删**。只配过 ``wecom_webhook`` 的部署升级后必须照常出声，
    否则这次改造会把一批线上告警静音，而且是静悄悄地静音——没人会收到
    「你的告警坏了」的告警。回归测试见 ``test_notify_channels.py``。
    """
    from src.ops.application.notify_registry import get_channel_config

    try:
        return str(get_channel_config(store, "wecom").get("url") or "").strip()
    except Exception as exc:  # noqa: BLE001 — 配置读坏了不该让整条推送崩掉
        logger.warning("resolve wecom url failed: %s", exc)
        return ""


def _resolve_channels(
    store: object,
    *,
    channel_ids: list[str] | None,
) -> list[dict[str, Any]]:
    channels = load_notify_channels(store)
    #  兼容：无 channels 表时回退企微单通道
    if not channels:
        url = _wecom_url(store)
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


def _normalize_level(level: str) -> str:
    return level if level in ("info", "warn", "critical") else "info"


def _fingerprint(title: str, body: str, level: str) -> str:
    """与新腿**同一份**指纹口径：title/level/body，不含 link。

    两条腿共用一个指纹，「同一条告警」在企微和钉钉那边才是同一件事；各算各的
    会让同一条消息在一个通道被压住、在另一个通道又冒出来。
    """
    from src.ops.domain.notify import NotifyMessage

    return NotifyMessage(title=title, body=body, level=level).fingerprint()  # type: ignore[arg-type]


def _dispatch_registry_channels(
    store: object,
    *,
    title: str,
    body: str,
    level: str,
    link: str,
    bypass_rate_limit: bool = False,
) -> tuple[list[str], list[str], list[str]]:
    """发给注册表里除企微外的已配置通道。永不抛，失败只记日志。"""
    from src.ops.application.notify_registry import dispatch_report
    from src.ops.domain.notify import NotifyMessage

    try:
        message = NotifyMessage(
            title=title,
            body=body,
            level=level,  # type: ignore[arg-type]
            link=link,
        )
        report = dispatch_report(
            store,
            message,
            channels=list(_EXTRA_CHANNELS),
            bypass_rate_limit=bypass_rate_limit,
        )
    except Exception as exc:  # noqa: BLE001 — 多通道出问题不许拖垮企微那条腿
        logger.warning("notify registry dispatch failed: %s", exc)
        return [], [], []
    suppressed = list(report.get("suppressed") or ())
    results = report.get("results") or {}
    sent = list(report.get("sent") or ())
    #  被限流的不算错：那是刻意不发，不是发失败。
    errors = [
        f"{name} 推送失败" for name, ok in results.items() if not ok and name not in set(suppressed)
    ]
    return sent, errors, suppressed


def dispatch_text(
    store: object,
    *,
    title: str,
    body: str,
    channel_ids: list[str] | None = None,
    bypass_quiet: bool = False,
    bypass_rate_limit: bool = False,
    webhook_override: str = "",
    prepend_title_to_wecom: bool = True,
    level: str = "info",
    link: str = "",
) -> dict[str, Any]:
    """向默认或指定渠道发送 text。

    两条腿，刻意分开：

    - **旧腿**（企微 / Bark）逐字保留。企微正文的 ``【标题】\\n正文`` 拼法、
      ``prepend_title_to_wecom`` 开关、出站队列串行 + 重试 3 次的语义都不许动——
      `jobs/notify` 与 `alert_rules` 的既有用例断言的就是这个字符串。
    - **新腿**：钉钉 / 飞书 / 通用 Webhook / 邮件 / 站内信经
      ``notify_registry.dispatch_report`` 并行发，各自 8s 超时、失败互不牵连。

    ``webhook_override`` 或显式 ``channel_ids`` 意味着调用方点名了要发哪儿，
    此时**不**外扩到新腿。

    ``bypass_rate_limit=True`` 只给「用户刚点了测试按钮」用（``/settings/notify/test``、
    ``/notify/channels/{name}/test``）：那时用户正盯着屏幕等回声，压住等于骗他
    「通道坏了」。**业务推送一律不许传 True。**

    返回值多了一个 ``suppressed``（本次被限流压住的通道名）。全部被压住时返回
    ``skipped="rate_limited"``——与 ``quiet_hours`` 同构，调用方能区分「刻意没发」
    和「发失败」，别把降噪记成故障。
    """
    from src.ops.application.notify_calendar import notification_silence_reason
    silence = notification_silence_reason()
    if silence:
        return {"success": False, "skipped": silence, "sent": [], "suppressed": []}
    policy = load_notify_policy(store)
    if not bypass_quiet and policy.is_quiet_now():
        return {"success": False, "skipped": "quiet_hours", "sent": [], "suppressed": []}

    channels = _resolve_channels(store, channel_ids=channel_ids)
    override = webhook_override.strip()
    if override:
        channels = [
            {
                "id": "wecom",
                "type": "wecom",
                "enabled": True,
                "is_default": True,
                "config": {"url": override},
            }
        ]

    level_name = _normalize_level(level)
    fingerprint = _fingerprint(title, body, level_name)
    #  一次分发内所有通道共用同一个 now：否则同一批里靠后的通道会因为多走了几十
    #  毫秒而落进不同的窗口，行为随机。
    now = time.time()

    def _gate(name: str) -> bool:
        """限流闸门。旧腿以前完全不问这一句，于是失败风暴能整天刷屏。"""
        if bypass_rate_limit:
            return True
        from src.ops.application.notify_registry import allow_send

        allowed = allow_send(name, fingerprint, now=now)
        if not allowed:
            logger.info("notify channel %s 被限流：60s 内同指纹已发过", name)
        return allowed

    sent: list[str] = []
    errors: list[str] = []
    suppressed: list[str] = []
    for channel in channels:
        ctype = str(channel.get("type") or "")
        config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
        try:
            if ctype == "wecom":
                url = str(config.get("url") or "").strip() or _wecom_url(store)
                if not url:
                    raise NotifyError("企微 Webhook 未配置")
                #  闸门放在 URL 解析之后：配置本身就坏时要报错，不能被限流盖成「已跳过」。
                if not _gate("wecom"):
                    suppressed.append("wecom")
                    continue
                #  企微无独立 title 字段；已自带标题的业务正文可显式关闭重复前缀。
                content = (
                    body
                    if not title or not prepend_title_to_wecom
                    else f"【{title}】\n{body}"
                )
                send_wecom_text(url, content)
                sent.append("wecom")
            elif ctype == "bark":
                if not _gate("bark"):
                    suppressed.append("bark")
                    continue
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

    if not override and not channel_ids:
        extra_sent, extra_errors, extra_suppressed = _dispatch_registry_channels(
            store,
            title=title,
            body=body,
            level=level_name,
            link=link,
            bypass_rate_limit=bypass_rate_limit,
        )
        sent.extend(extra_sent)
        errors.extend(extra_errors)
        suppressed.extend(extra_suppressed)

    if not sent and not errors and suppressed:
        #  「刻意没发」不是「发失败」。调用方（jobs/notify、execute_notify）据此
        #  记 push_skipped 而不是 push_error，运维页才不会满屏假故障。
        return {
            "success": False,
            "skipped": "rate_limited",
            "sent": [],
            "suppressed": suppressed,
        }

    if not sent and not errors:
        return {
            "success": False,
            "error": "没有可用的通知渠道（Webhook 未配置）",
            "sent": [],
            "suppressed": suppressed,
        }

    return {
        "success": bool(sent) and not errors,
        "partial": bool(sent) and bool(errors),
        "sent": sent,
        "errors": errors,
        "suppressed": suppressed,
    }
