"""六个告警通道 + 可插拔注册表。

设计约束（每条都有过血的教训）：

1. **一个通道挂不能带死任务。** 所有 ``send`` 都吞异常返回 False，只记
   WARNING。推送是任务的副产品，不是任务本身——`jobs/notify` 那边已经因为
   一条推送异常把整次运行卡在 ``running`` 上收不了尾过一回。
2. **超时统一 8s。** 六个通道串起来最坏 48s；再长就会顶到调度器的心跳窗。
3. **企微不重写。** ``WecomChannel`` 直接转调 ``application.notify.send_wecom_text``，
   payload（msgtype=text）、2000 字截断、出站队列串行 + 失败重试 3 次的语义
   原样保留。这里只是给它套一层通道壳，不是第二个企微实现。

出站 IO 收在 ``_http_post_json`` / ``_smtp_send`` 两个私有函数里，测试打这两个
桩即可，不必去够 urllib（仓内既有约定，见 ``notify._post``）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import smtplib
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from email.message import EmailMessage
from typing import Any

from src.ops.domain.notify import NotifyMessage

logger = logging.getLogger(__name__)

__all__ = [
    "CHANNEL_TIMEOUT_SEC",
    "SECRET_FIELDS",
    "channel_names",
    "dingtalk_signature",
    "feishu_signature",
    "get_channel",
    "iter_channels",
]

#: 单通道出站超时。见模块头第 2 条。
CHANNEL_TIMEOUT_SEC = 8
#: 群机器人类通道的正文上限，与企微既有实现对齐。
MAX_TEXT_CHARS = 2000

#: 每个通道里**不许回显**的配置键。应用层据此只回末 6 位。
SECRET_FIELDS: Mapping[str, tuple[str, ...]] = {
    "wecom": ("url",),
    "dingtalk": ("url", "secret"),
    "feishu": ("url", "secret"),
    "webhook": ("url",),
    "email": (),
    "inbox": (),
}


def _clip(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 12] + "\n…(已截断)"


def _http_post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """POST 一份 JSON 并解析响应。失败抛异常，由各通道的 ``send`` 兜住。

    独立成函数是为了给测试一个桩点：外部 HTTP 必须 mock，但没人应该为了
    mock 一次推送去理解 urllib 的异常谱系。
    """
    body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
    merged = {"Content-Type": "application/json; charset=utf-8"}
    merged.update({str(k): str(v) for k, v in (headers or {}).items()})
    request = urllib.request.Request(url, data=body, headers=merged, method="POST")
    with urllib.request.urlopen(request, timeout=CHANNEL_TIMEOUT_SEC) as response:
        raw = response.read().decode("utf-8", errors="replace")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # 通用 Webhook 的对端未必回 JSON；HTTP 2xx 就算送到了。
        return {"raw": raw[:200]}
    return parsed if isinstance(parsed, dict) else {"raw": raw[:200]}


def dingtalk_signature(secret: str, timestamp_ms: int) -> str:
    """钉钉自定义机器人加签：``HMAC-SHA256(secret, f"{ts}\\n{secret}")``。

    注意签名串与密钥**都是** secret，官方文档如此；base64 之后还要再
    urlencode 一次才能进 query。
    """
    string_to_sign = f"{timestamp_ms}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))


def feishu_signature(secret: str, timestamp_s: int) -> str:
    """飞书自定义机器人加签，与钉钉**不是**同一套。

    飞书把 ``f"{ts}\\n{secret}"`` 当作 HMAC 的**密钥**，对**空消息体**取
    HMAC-SHA256；钉钉则是拿 secret 当密钥对该串取签。照抄另一家会一直 401。
    """
    string_to_sign = f"{timestamp_s}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


class _BaseChannel:
    """通道公共壳：把 ``send`` 的「永不抛」契约收在一处。"""

    name = ""
    label = ""

    def is_configured(self, config: Mapping[str, Any]) -> bool:
        raise NotImplementedError

    def _deliver(self, message: NotifyMessage, config: Mapping[str, Any]) -> None:
        raise NotImplementedError

    def send(self, message: NotifyMessage, config: Mapping[str, Any]) -> bool:
        if not self.is_configured(config):
            logger.warning("notify channel %s skipped: not configured", self.name)
            return False
        try:
            self._deliver(message, config)
        except Exception as exc:  # noqa: BLE001 — 单通道故障不许外溢
            logger.warning(
                "notify channel %s failed: %s: %s", self.name, type(exc).__name__, exc
            )
            return False
        return True


class WecomChannel(_BaseChannel):
    """企业微信群机器人。**封装既有实现**，不重写 payload 与限额语义。"""

    name = "wecom"
    label = "企业微信"

    def is_configured(self, config: Mapping[str, Any]) -> bool:
        return bool(str(config.get("url") or "").strip())

    def _deliver(self, message: NotifyMessage, config: Mapping[str, Any]) -> None:
        # 延迟 import：application.notify 侧的注册表会反向引用本模块，
        # 顶层 import 会成环。顺带保证企微行为只有一份实现。
        from src.ops.application.notify import send_wecom_text

        send_wecom_text(str(config.get("url") or "").strip(), message.as_text())


class DingTalkChannel(_BaseChannel):
    """钉钉自定义机器人（可选加签）。"""

    name = "dingtalk"
    label = "钉钉"

    def is_configured(self, config: Mapping[str, Any]) -> bool:
        return bool(str(config.get("url") or "").strip())

    def _deliver(self, message: NotifyMessage, config: Mapping[str, Any]) -> None:
        url = str(config.get("url") or "").strip()
        secret = str(config.get("secret") or "").strip()
        if secret:
            timestamp = int(time.time() * 1000)
            sign = dingtalk_signature(secret, timestamp)
            joiner = "&" if "?" in url else "?"
            url = f"{url}{joiner}timestamp={timestamp}&sign={sign}"
        text = _clip(message.as_text())
        keyword = str(config.get("keyword") or "").strip()
        if keyword:
            # 钉钉「自定义关键词」安全设置：正文不含关键词会被对端静默丢弃。
            text = _clip(f"{keyword} {text}")
        payload = {"msgtype": "text", "text": {"content": text}}
        data = _http_post_json(url, payload)
        if int(data.get("errcode", 0) or 0) != 0:
            raise RuntimeError(f"钉钉错误 {data.get('errcode')}：{data.get('errmsg', '')}")


class FeishuChannel(_BaseChannel):
    """飞书自定义机器人（可选加签）。"""

    name = "feishu"
    label = "飞书"

    def is_configured(self, config: Mapping[str, Any]) -> bool:
        return bool(str(config.get("url") or "").strip())

    def _deliver(self, message: NotifyMessage, config: Mapping[str, Any]) -> None:
        url = str(config.get("url") or "").strip()
        secret = str(config.get("secret") or "").strip()
        payload: dict[str, Any] = {
            "msg_type": "text",
            "content": {"text": _clip(message.as_text())},
        }
        if secret:
            timestamp = int(time.time())
            payload["timestamp"] = str(timestamp)
            payload["sign"] = feishu_signature(secret, timestamp)
        data = _http_post_json(url, payload)
        # 飞书成功回 code=0；老接口回 StatusCode=0。两种都认。
        code = data.get("code", data.get("StatusCode", 0))
        if int(code or 0) != 0:
            detail = data.get("msg", data.get("StatusMessage", ""))
            raise RuntimeError(f"飞书错误 {code}：{detail}")


class WebhookChannel(_BaseChannel):
    """通用 Webhook：POST 结构化 JSON，headers 可自定义。

    正文发结构化字段而不是拼好的 text——对端多半是自家网关/告警平台，
    需要 level 和 tags 做路由；要纯文本的话 ``text`` 字段也一并给了。
    """

    name = "webhook"
    label = "通用 Webhook"

    def is_configured(self, config: Mapping[str, Any]) -> bool:
        return bool(str(config.get("url") or "").strip())

    def _deliver(self, message: NotifyMessage, config: Mapping[str, Any]) -> None:
        raw_headers = config.get("headers")
        headers = raw_headers if isinstance(raw_headers, Mapping) else {}
        _http_post_json(
            str(config.get("url") or "").strip(),
            {
                "title": message.title,
                "body": message.body,
                "level": message.level,
                "link": message.link,
                "tags": list(message.tags),
                "text": message.as_text(),
            },
            headers=headers,
        )


def _smtp_send(*, host: str, port: int, use_ssl: bool, user: str, password: str,
    message: EmailMessage) -> None:
    """SMTP 出站的唯一入口（测试桩点）。"""
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=CHANNEL_TIMEOUT_SEC) as client:
            if user:
                client.login(user, password)
            client.send_message(message)
        return
    with smtplib.SMTP(host, port, timeout=CHANNEL_TIMEOUT_SEC) as client:
        client.starttls()
        if user:
            client.login(user, password)
        client.send_message(message)


class EmailChannel(_BaseChannel):
    """邮件（stdlib smtplib）。

    读的是 identity 那套 ``LOCI_SMTP_*`` 环境变量，但**不复用它的 Mailer**：
    ``Mailer`` 没从 ``src.identity`` 包根导出，深引 infrastructure 会撞
    ``protect-identity-infra`` 契约。收件人由通道配置给（``to``），
    SMTP 凭据仍走环境变量——密码不进 ops.db。
    """

    name = "email"
    label = "邮件"

    def _recipients(self, config: Mapping[str, Any]) -> list[str]:
        raw = config.get("to")
        if isinstance(raw, str):
            items = [part for part in raw.replace(";", ",").split(",")]
        elif isinstance(raw, (list, tuple)):
            items = [str(part) for part in raw]
        else:
            items = []
        return [item.strip() for item in items if item.strip()]

    def is_configured(self, config: Mapping[str, Any]) -> bool:
        host = os.environ.get("LOCI_SMTP_HOST", "").strip()
        sender = (
            os.environ.get("LOCI_SMTP_FROM", "").strip()
            or os.environ.get("LOCI_SMTP_USER", "").strip()
        )
        return bool(host and sender and self._recipients(config))

    def _deliver(self, message: NotifyMessage, config: Mapping[str, Any]) -> None:
        host = os.environ.get("LOCI_SMTP_HOST", "").strip()
        port = int(os.environ.get("LOCI_SMTP_PORT", "465") or 465)
        user = os.environ.get("LOCI_SMTP_USER", "").strip()
        password = os.environ.get("LOCI_SMTP_PASSWORD", "").strip()
        sender = os.environ.get("LOCI_SMTP_FROM", "").strip() or user
        use_ssl = (os.environ.get("LOCI_SMTP_SSL", "1").strip() or "1") not in ("0", "false")
        recipients = self._recipients(config)

        mail = EmailMessage()
        mail["From"] = sender
        mail["To"] = ", ".join(recipients)
        mail["Subject"] = f"[{message.level.upper()}] {message.title}" if message.title else "Loci 告警"
        mail.set_content(message.as_text())
        _smtp_send(
            host=host,
            port=port,
        use_ssl=use_ssl,
            user=user,
            password=password,
            message=mail,
        )


class InboxChannel(_BaseChannel):
    """站内信：写 identity.db 的 ``notifications`` 表。

    经 ``from src.identity import IdentityStore`` 包根导入——深引
    ``identity.infrastructure`` 会被 import-linter 拦下。
    """

    name = "inbox"
    label = "站内信"

    def _user_ids(self, config: Mapping[str, Any]) -> list[str]:
        raw = config.get("user_ids")
        if isinstance(raw, str):
            items = [part for part in raw.replace(";", ",").split(",")]
        elif isinstance(raw, (list, tuple)):
            items = [str(part) for part in raw]
        else:
            items = []
        return [item.strip() for item in items if item.strip()]

    def is_configured(self, config: Mapping[str, Any]) -> bool:
        return bool(self._user_ids(config))

    def _deliver(self, message: NotifyMessage, config: Mapping[str, Any]) -> None:
        from src.identity import IdentityStore

        db_path = str(config.get("identity_db") or "").strip() or None
        kind = str(config.get("kind") or "").strip() or "alert"
        with IdentityStore(db_path) as store:
            for user_id in self._user_ids(config):
                store.push_notification(
                    user_id=user_id,
                    title=message.title or "Loci 告警",
                    body=message.body,
                    kind=kind,
                    link=message.link,
                )


#: 通道注册表。加通道 = 在这里加一行；应用层与 HTTP 层都按 name 索引，
#: 不再有第二处 if/elif 需要同步（旧的 ``notify_dispatch`` 就是那样长歪的）。
_CHANNELS: dict[str, _BaseChannel] = {
    channel.name: channel
    for channel in (
        WecomChannel(),
        DingTalkChannel(),
        FeishuChannel(),
        WebhookChannel(),
        EmailChannel(),
        InboxChannel(),
    )
}


def get_channel(name: str) -> _BaseChannel | None:
    return _CHANNELS.get((name or "").strip().lower())


def channel_names() -> list[str]:
    """注册顺序即展示顺序（企微在前，兼容老部署的心智）。"""
    return list(_CHANNELS)


def iter_channels() -> list[_BaseChannel]:
    return list(_CHANNELS.values())
