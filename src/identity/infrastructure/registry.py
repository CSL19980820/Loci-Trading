"""provider 注册表 + 邮件发送。

注册表的唯一对外出口是 ``enabled_providers()``：**白名单 ∩ 凭据齐备**。
``LOCI_AUTH_PROVIDERS`` 逗号分隔，默认 ``email,mock``。上线顺序因此是纯配置：
``email,mock`` → ``email,qq_web`` → ``email,qq_web,wechat_web``，代码零改动。

邮件：默认**控制台通道**（把验证码打到日志），配了 SMTP 才真发。
这样开发机与 CI 不需要任何外部依赖就能跑通注册全链路，
而生产只要填 4 个环境变量。发信失败不吞——注册流程要能如实告诉用户。
"""
from __future__ import annotations

from email.message import EmailMessage
from typing import Any
import logging
import os
import smtplib

from src.identity.domain.providers import OAuthProvider, provider_card
from src.identity.infrastructure.oauth_providers import (
    MockScanProvider,
    QQWebProvider,
    WeChatWebProvider,
)

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, OAuthProvider] = {
    "wechat_web": WeChatWebProvider(),
    "qq_web": QQWebProvider(),
    "mock": MockScanProvider(),
}


def _allowlist() -> set[str]:
    raw = os.environ.get("LOCI_AUTH_PROVIDERS", "email,mock")
    return {item.strip() for item in raw.split(",") if item.strip()}


def enabled_providers() -> list[OAuthProvider]:
    """当前真正可用的外部 provider。``email`` 不在这里——它不是 OAuth。"""
    allowed = _allowlist()
    return [
        provider
        for name, provider in _REGISTRY.items()
        if name in allowed and provider.is_configured()
    ]


def get_provider(name: str) -> OAuthProvider | None:
    provider = _REGISTRY.get(name)
    if provider is None:
        return None
    if name not in _allowlist() or not provider.is_configured():
        return None
    return provider


#: 自助注册开关认这些字面量为「开」。缺省（未设置 / 空 / 其它值）一律为关。
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def signup_enabled() -> bool:
    """是否开放**邮箱自助注册**。

    **缺省关闭**：本系统不走注册制，账号由管理员在管理后台新增。
    只有显式把 ``LOCI_ALLOW_SIGNUP`` 置为 ``1/true/yes/on``（大小写不敏感）
    才放开自助注册。

    刻意与 ``LOCI_AUTH_PROVIDERS`` 里的 ``email`` 解耦：``email`` 决定的是
    「能不能用邮箱+口令**登录**」，注册是另一回事——管理员开的号也要用邮箱登。
    """
    return os.environ.get("LOCI_ALLOW_SIGNUP", "").strip().lower() in _TRUTHY


def login_options() -> dict[str, Any]:
    """登录页需要知道的一切。绝不含任何 secret。"""
    return {
        "email_signup": signup_enabled(),
        "providers": [provider_card(provider) for provider in enabled_providers()],
    }


def public_base_url() -> str:
    """对外可访问的站点根。

        **绝不从 Host 头推导**——OWASP 点名的 Host Header Injection 会让攻击者
        把密码重置链接指向自己的域名。宁可链接不可点，也不能可点到别人家。
        """
    return os.environ.get("LOCI_PUBLIC_BASE_URL", "").strip().rstrip("/")


class Mailer:
    """发信通道。SMTP 未配置时退化为「写日志」，链路照样跑通。"""

    def __init__(self) -> None:
        self.host = os.environ.get("LOCI_SMTP_HOST", "").strip()
        self.port = int(os.environ.get("LOCI_SMTP_PORT", "465") or 465)
        self.user = os.environ.get("LOCI_SMTP_USER", "").strip()
        self.password = os.environ.get("LOCI_SMTP_PASSWORD", "").strip()
        self.sender = os.environ.get("LOCI_SMTP_FROM", "").strip() or self.user
        self.use_ssl = (os.environ.get("LOCI_SMTP_SSL", "1").strip() or "1") not in ("0", "false")

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)

    def send(self, *, to: str, subject: str, body: str) -> bool:
        """返回是否真的经 SMTP 发出。控制台通道返回 False 但不算失败。"""
        if not self.configured:
            # 开发/CI：把内容原样打到日志，人工复制验证码即可完成注册。
            logger.warning("[mail:console] to=%s subject=%s\n%s", to, subject, body)
            return False
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        if self.use_ssl:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=15) as client:
                if self.user:
                    client.login(self.user, self.password)
                client.send_message(message)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=15) as client:
                client.starttls()
                if self.user:
                    client.login(self.user, self.password)
                client.send_message(message)
        return True


def render_verification_mail(*, code: str, token: str, purpose: str) -> tuple[str, str]:
    """返回 ``(subject, body)``。链接与验证码同时给，用户挑顺手的用。"""
    base = public_base_url()
    if purpose == "reset":
        subject = "【Loci】重置密码验证码"
        path = f"{base}/login?reset_token={token}" if base else ""
        lead = "你正在重置 Loci 账号密码。若不是本人操作请忽略本邮件。"
        valid = "30 分钟"
    else:
        subject = "【Loci】邮箱验证码"
        path = f"{base}/login?verify_token={token}" if base else ""
        lead = "欢迎加入 Loci 量化工作台。请验证你的邮箱以启用全部功能。"
        valid = "24 小时"
    lines = [lead, "", f"验证码：{code}", f"有效期：{valid}"]
    if path:
        lines.extend(["", f"也可以直接点击：{path}"])
    lines.extend(["", "—— Loci 潜龙量化"])
    return subject, "\n".join(lines)
