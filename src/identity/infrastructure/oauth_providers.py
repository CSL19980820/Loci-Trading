"""外部登录提供方的真实现：微信网站应用、QQ 互联、以及开发用 mock。

**为什么三个实现放一个文件**：它们共享同一套 httpx 调用姿势与错误映射，
拆开只会让三份「读环境变量 → 拼 URL → 解析 errcode」互相漂移。
单个 provider 的代码量都不到 80 行，合起来仍远低于 600 行上限。

调研依据（2026-08）：

- 微信：``https://open.weixin.qq.com/connect/qrconnect``，``scope`` 目前仅
  ``snsapi_login``；``#wechat_redirect`` 锚点必须保留；``code`` 10 分钟且只能
  兑换一次；``unionid`` **当且仅当已获得 userinfo 授权时才出现**，必须容忍缺失；
  ``sns/userinfo`` 的 ``lang`` 默认是 en，要显式传 ``zh_CN``；
  性别/地区字段自 2021-10-20 起不再返回；**头像 URL 会在用户换头像后失效**。
- QQ：``https://graph.qq.com/oauth2.0/authorize``；token 与 me 两个接口
  **默认不是 JSON**（分别是 x-www-form-urlencoded 与 jsonpb），必须显式
  ``fmt=json``；``need_openid=1`` 可省一次往返；头像取 ``figureurl_qq_1``
  （官方称一定会有）；性别/地区是脱敏假数据，业务不得依赖。

没有 appid/secret 时 ``is_configured()`` 返回 False，provider 不会出现在
登录页上——**这就是「资质没下来也能上线」的全部机制**。
"""
from __future__ import annotations

from typing import Any
import os
import urllib.parse

from src.identity.domain.providers import (
    AuthzChallenge,
    ExternalIdentity,
    ProviderError,
    ProviderNotConfigured,
)

_TIMEOUT_SEC = 8.0


def _http_get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """统一的厂商 GET。httpx2 是本仓既有依赖，不再引入新的 HTTP 客户端。"""
    try:
        import httpx2 as httpx
    except ImportError:  # pragma: no cover - 环境缺依赖时给出可读原因
        try:
            import httpx  # type: ignore[no-redef]
        except ImportError as exc:
            raise ProviderNotConfigured("缺少 HTTP 客户端依赖（httpx2）") from exc
    with httpx.Client(timeout=_TIMEOUT_SEC, trust_env=False) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        text = response.text.strip()
    try:
        return response.json()
    except ValueError as exc:
        # QQ 的 me 接口不带 fmt 时返回 `callback( {...} );`——这里兜一层，
        # 但正常路径应该永远带 fmt=json。
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            import json

            return dict(json.loads(text[start : end + 1]))
        raise ProviderError(
            "unknown", "bad_payload", f"非 JSON 响应：{text[:120]}"
        ) from exc


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


class WeChatWebProvider:
    """微信开放平台「网站应用微信登录」。整页跳转形态，厂商 302 回调。"""

    name = "wechat_web"
    family = "wechat"
    login_mode = "redirect"
    label = "微信登录"

    def is_configured(self) -> bool:
        return bool(_env("LOCI_WECHAT_APPID") and _env("LOCI_WECHAT_SECRET"))

    def start(self, *, state: str, redirect_uri: str) -> AuthzChallenge:
        if not self.is_configured():
            raise ProviderNotConfigured("微信登录未配置 appid/secret")
        query = urllib.parse.urlencode(
            {
                "appid": _env("LOCI_WECHAT_APPID"),
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "snsapi_login",
                "state": state,
                "lang": "cn",
            }
        )
        # 锚点 #wechat_redirect 是微信侧的硬要求，丢了会拿到空白页。
        url = f"https://open.weixin.qq.com/connect/qrconnect?{query}#wechat_redirect"
        return AuthzChallenge(state=state, mode="redirect", redirect_url=url, expires_in=600)

    def exchange(self, *, code: str, state: str, redirect_uri: str) -> ExternalIdentity:
        if not self.is_configured():
            raise ProviderNotConfigured("微信登录未配置 appid/secret")
        token = _http_get_json(
            "https://api.weixin.qq.com/sns/oauth2/access_token",
            {
                "appid": _env("LOCI_WECHAT_APPID"),
                "secret": _env("LOCI_WECHAT_SECRET"),
                "code": code,
                "grant_type": "authorization_code",
            },
        )
        if token.get("errcode"):
            raise ProviderError(self.name, token["errcode"], str(token.get("errmsg", "")))
        openid = str(token.get("openid") or "")
        if not openid:
            raise ProviderError(self.name, "no_openid", "微信未返回 openid")
        profile = _http_get_json(
            "https://api.weixin.qq.com/sns/userinfo",
            {
                "access_token": token.get("access_token", ""),
                "openid": openid,
                # 默认是 en，会拿到一串问号昵称。
                "lang": "zh_CN",
            },
        )
        if profile.get("errcode"):
            # 拿不到资料不该挡住登录：openid 已经足以确认身份。
            profile = {}
        return ExternalIdentity(
            provider=self.name,
            family="wechat",
            subject=openid,
            union_key=str(profile.get("unionid") or token.get("unionid") or "") or None,
            display_name=str(profile.get("nickname") or ""),
            avatar_url=str(profile.get("headimgurl") or ""),
            raw={"scope": token.get("scope", "")},
        )


class QQWebProvider:
    """QQ 互联网站应用登录。整页跳转形态。

        比微信友好的一点：官方 FAQ 明确「创建应用后便可以立即获取 appkey 和
        appid」，未过审的应用可以用注册者本人的 QQ 号真机跑通全链路。
      """

    name = "qq_web"
    family = "qq"
    login_mode = "redirect"
    label = "QQ 登录"

    def is_configured(self) -> bool:
        return bool(_env("LOCI_QQ_APPID") and _env("LOCI_QQ_APPKEY"))

    def start(self, *, state: str, redirect_uri: str) -> AuthzChallenge:
        if not self.is_configured():
            raise ProviderNotConfigured("QQ 登录未配置 appid/appkey")
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": _env("LOCI_QQ_APPID"),
                "redirect_uri": redirect_uri,
                # state 在 QQ 侧是「必须」而非可选，文档要求严格绑定用户与 state。
                "state": state,
                "scope": "get_user_info",
            }
        )
        url = f"https://graph.qq.com/oauth2.0/authorize?{query}"
        return AuthzChallenge(state=state, mode="redirect", redirect_url=url, expires_in=600)

    def exchange(self, *, code: str, state: str, redirect_uri: str) -> ExternalIdentity:
        if not self.is_configured():
            raise ProviderNotConfigured("QQ 登录未配置 appid/appkey")
        appid = _env("LOCI_QQ_APPID")
        token = _http_get_json(
            "https://graph.qq.com/oauth2.0/token",
            {
                "grant_type": "authorization_code",
                "client_id": appid,
                "client_secret": _env("LOCI_QQ_APPKEY"),
                "code": code,
                "redirect_uri": redirect_uri,
                # 不带 fmt 会拿到 x-www-form-urlencoded，解析必挂。
                "fmt": "json",
                # 顺带把 openid 带回来，省一次 me 调用。
                "need_openid": "1",
            },
        )
        if token.get("error"):
            raise ProviderError(self.name, token["error"], str(token.get("error_description", "")))
        access_token = str(token.get("access_token") or "")
        openid = str(token.get("openid") or "")
        unionid = str(token.get("unionid") or "")
        if not openid:
            me = _http_get_json(
                "https://graph.qq.com/oauth2.0/me",
                {"access_token": access_token, "unionid": "1", "fmt": "json"},
            )
            if me.get("error"):
                raise ProviderError(self.name, me["error"], str(me.get("error_description", "")))
            openid = str(me.get("openid") or "")
            unionid = unionid or str(me.get("unionid") or "")
        if not openid:
            raise ProviderError(self.name, "no_openid", "QQ 未返回 openid")
        profile = _http_get_json(
            "https://graph.qq.com/user/get_user_info",
            {"access_token": access_token, "oauth_consumer_key": appid, "openid": openid},
        )
        if int(profile.get("ret", 0) or 0) != 0:
            # 拿不到资料不该挡住登录：openid 已经足以确认身份。
            profile = {}
        return ExternalIdentity(
            provider=self.name,
            family="qq",
            subject=openid,
            union_key=unionid or None,
            display_name=str(profile.get("nickname") or ""),
            # figureurl_qq_1 是官方声明「一定会有」的那张 40x40。
            avatar_url=str(profile.get("figureurl_qq_1") or profile.get("figureurl_qq_2") or ""),
            raw={},
        )


class MockScanProvider:
    """开发/演示用的扫码登录。二维码内容指向本站的确认页。

        生产环境恒不可用——``is_configured`` 在 production 下直接返回 False，
        **且刻意不提供任何 override 开关**。这是安全底线：一个能凭空造账号的
        provider 只要留一个开关，就一定有一天被打开。
        """

    name = "mock"
    family = "mock"
    login_mode = "qrcode"
    label = "演示扫码"

    def is_configured(self) -> bool:
        environment = (os.environ.get("PALACE_ENV") or "local").strip().lower()
        if environment == "production":
            return False
        return True

    def start(self, *, state: str, redirect_uri: str) -> AuthzChallenge:
        base = _env("LOCI_PUBLIC_BASE_URL") or ""
        content = f"{base}/login?mock_state={urllib.parse.quote(state)}"
        return AuthzChallenge(
            state=state,
            mode="qrcode",
            qr_content=content,
            expires_in=300,
        )

    def exchange(self, *, code: str, state: str, redirect_uri: str) -> ExternalIdentity:
        """``code`` 就是演示用的昵称；不同 code 造出不同的稳定 subject。"""
        handle = (code or "demo").strip()[:32] or "demo"
        return ExternalIdentity(
            provider=self.name,
            family="mock",
            subject=f"mock:{handle}",
            union_key=None,
            display_name=handle,
            avatar_url="",
            raw={"mock": True},
        )
