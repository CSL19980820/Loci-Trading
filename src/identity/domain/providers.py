"""外部登录提供方的可插拔契约。

为什么先有契约再有实现：微信/QQ 开放平台都要**主体资质 + 应用审核**才能拿到
appid/secret。资质没下来之前，整条链路必须能跑通，否则等审核过了才发现
状态机有 bug，代价高得多。于是：

- 契约在 domain（这里），不依赖 httpx；
- 真实现（微信/QQ）与 mock 实现都在 infrastructure，同构；
- 启用哪些 provider 由 ``LOCI_AUTH_PROVIDERS`` 环境变量决定，改配置不改代码；
- ``mock`` provider 在 production 下 ``is_configured()`` 恒为 False，没有 override。

两种登录形态：

- ``redirect``：整页跳到厂商授权页（微信 qrconnect / QQ authorize），厂商 302 回来。
  前端不需要轮询，但我们仍然登记 state，以便回调时确认是自己发起的。
- ``qrcode``：我们自己出二维码，用户扫完由厂商推事件或用户点确认。前端要轮询。

两种形态共用同一套 ``oauth_states`` 状态机，前端只按 ``mode`` 决定画什么。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any, Literal, Protocol, runtime_checkable

from src.identity.domain.models import IdentityError, ProviderFamily

LoginMode = Literal["redirect", "qrcode"]


class ProviderError(IdentityError):
    """厂商侧返回的错误。``code`` 保留厂商原始码，方便对着文档排查。"""

    code = "provider_error"
    http_status = 502

    def __init__(self, provider: str, code: str | int, message: str) -> None:
        super().__init__(f"[{provider}:{code}] {message}")
        self.provider = provider
        self.provider_code = str(code)
        self.provider_message = message


class ProviderNotConfigured(IdentityError):
    code = "provider_not_configured"
    http_status = 503


@dataclass(frozen=True, slots=True)
class AuthzChallenge:
    """发起一次登录后交给前端的东西。"""

    state: str
    mode: LoginMode
    redirect_url: str | None = None
    qr_image_url: str | None = None
    qr_content: str | None = None
    expires_in: int = 300

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "mode": self.mode,
            "redirect_url": self.redirect_url,
            "qr_image_url": self.qr_image_url,
            "qr_content": self.qr_content,
            "expires_in": self.expires_in,
        }


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    """从厂商换回来的身份。``union_key`` 可能为 None——调用方必须容忍。

        微信新版文档写明 unionid「当且仅当该网站应用已获得该用户的 userinfo 授权时
        才会出现」；QQ 的 unionid 要单独申请权限。把它当必填字段会在生产上炸。
        """

    provider: str
    family: ProviderFamily
    subject: str
    union_key: str | None = None
    display_name: str = ""
    avatar_url: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class OAuthProvider(Protocol):
    """一个外部登录方式。实现放 infrastructure。"""

    name: str
    family: ProviderFamily
    login_mode: LoginMode
    label: str

    def is_configured(self) -> bool:
        """凭据齐备且当前环境允许启用。"""
        ...

    def start(self, *, state: str, redirect_uri: str) -> AuthzChallenge:
        """发起授权。``state`` 由调用方生成并已登记进库。"""
        ...

    def exchange(self, *, code: str, state: str, redirect_uri: str) -> ExternalIdentity:
        """用回调拿到的 code 换取身份。失败抛 ``ProviderError``。"""
        ...


def provider_card(provider: OAuthProvider) -> dict[str, Any]:
    """给前端登录页画按钮用的名片。绝不含 secret。"""
    return {
        "name": provider.name,
        "family": provider.family,
        "label": provider.label,
        "mode": provider.login_mode,
    }
