"""助手只读外网工具：web_search / web_fetch（常见开源 Agent 能力面）。

设计对齐主流开源 Agent / MCP 检索工具的最小交集：
查询 → 标题/链接/摘要；可选抓取可读正文；结果标明「外网证据 · 非账本数字」。
不引入付费 API Key；失败时清晰回退，不编造结果。

SSRF：``web_fetch`` 注册为 ``write=False``，LLM（含只读子 Agent）不需要
ExecutionGrant 就能直接点名 URL。本仓还会经 ``deploy/`` 上公网服务器，那边
169.254.169.254 真能换出云凭据。所以出站目标一律**解析成 IP 后**用
``ipaddress`` 判是不是公网，且**每一跳重定向都重判**（见 ``_get_guarded``）。
"""
from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import os
from ipaddress import IPv6Address, ip_address, ip_network
import re
import socket
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx2

from src.ai.application.system_toolbus import ToolResult, ToolSpec, _object, _ok


_UA = (
    "Mozilla/5.0 (compatible; LociAssistant/1.0; +https://github.com/local/loci)"
)
_TIMEOUT = 18.0
_MAX_RESULTS = 8
_MAX_FETCH_CHARS = 12_000

#: 外网工具**专用**代理。为什么不复用全局 ``HTTP_PROXY``:同一个进程还要拉
#: akshare / 腾讯 / 新浪 / 通达信这些**国内**行情源,全局代理会把它们一起绕到
#: 境外出口——又慢又容易直接断,而行情是这套系统的命根子。所以只给这两个
#: 外网工具单开一个开关,行情链路一律直连。
#:
#: 生产实测(2026-08-26,容器内):直连 ``html.duckduckgo.com`` 报
#: ``Network is unreachable``;经宿主 ``172.17.0.1:7890`` 380ms 拿到 HTTP 202。
#: 不配置时行为完全不变(``proxy=None`` → httpx 仍按 ``trust_env`` 读全局环境
#: 变量),开发机上原来怎么走现在还怎么走。
_PROXY_ENV = "LOCI_WEB_TOOL_PROXY"


#: 重定向跳数上限。httpx 的 follow_redirects 已关闭，改由 _get_guarded 手动跟。
_MAX_REDIRECTS = 5
#: Clash / Surge Fake-IP 段（RFC 2544 基准网）。国内基本要挂代理才够得到
#: duckduckgo，而 Fake-IP 模式下域名会先解析到这里再由代理出站——它是代理
#: 产物，不是内网 SSRF。与 src/intel 的 MCP 校验同口径（那边注释详述）。
#: 例外只给 DNS 名；调用方直接写 198.18.x.x 字面量仍然拒绝。
_PROXY_FAKE_IP_NETWORKS = (ip_network("198.18.0.0/15"),)
#: 拒绝文案对模型和用户都可见：说清楚拒了什么，但不回显解析到的地址，
#: 免得把 web_fetch 变成一台内网拓扑探测器（拒绝详情本身就是探测结果）。
_BLOCK_HINT = "目标地址不是公网地址（本机 / 内网 / 链路本地 / 云元数据 / 保留段），已拒绝"
#: 本机与局域网常见后缀：解析器可能答得出也可能答不出，先按字面拦一道。
_LOCAL_HOST_SUFFIXES = (".local", ".localhost", ".internal", ".home.arpa")


def _err(message: str) -> ToolResult:
    return {"text": message, "is_error": True}


class WebAccessBlocked(ValueError):
    """出站目标被 SSRF 护栏拒绝。消息给人看，不含解析到的具体地址。"""


def _canonical_ip(host: str) -> Any | None:
    """主机名字面量 → IP；ipaddress 不认、但系统解析器认的简写也要认。

    ``127.1`` / ``2130706433`` / ``0x7f.0.0.1`` 都会被 inet_aton 还原成
    127.0.0.1。只用 ``ip_address()`` 会把它们当普通域名丢给 DNS 那一路，于是
    「拦没拦住」变成看操作系统脸色：Windows 上 getaddrinfo("127.1") 直接失败，
    Linux 上却老老实实连回本机。
    """
    text = host.split("%", 1)[0]  # 去掉 IPv6 zone id
    try:
        return ip_address(text)
    except ValueError:
        pass
    try:
        packed = socket.inet_aton(text)
    except OSError:
        return None
    return ip_address(int.from_bytes(packed, "big"))


def _embedded_addresses(address: Any) -> list[Any]:
    """IPv4-mapped / 6to4 / Teredo：v6 字面量里可能藏着一个 v4 内网地址。"""
    out = [address]
    if isinstance(address, IPv6Address):
        out.extend(item for item in (address.ipv4_mapped, address.sixtofour) if item)
        if address.teredo:
            out.extend(address.teredo)
    return out


def _is_public_address(address: Any) -> bool:
    """只认可路由的公网地址；不自己拼网段表，用 ipaddress 的内置判定。"""
    for candidate in _embedded_addresses(address):
        if (
            candidate.is_loopback
            or candidate.is_private
            or candidate.is_link_local
            or candidate.is_reserved
            or candidate.is_multicast
            or candidate.is_unspecified
        ):
            return False
        # 上述属性有盲区（如 CGNAT 100.64/10 在 CPython 里 is_private=False），
        # is_global 兜底：拿不准的一律当非公网拒掉。
        if not candidate.is_global:
            return False
    return True


def _is_proxy_fake_ip(address: Any) -> bool:
    try:
        return any(address in network for network in _PROXY_FAKE_IP_NETWORKS)
    except TypeError:  # v6 地址与 v4 网段比较
        return False


def _resolve_addresses(host: str, port: int) -> set[Any]:
    """解析 A/AAAA。只看字面主机名拦不住「域名指向内网」这一路。"""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise WebAccessBlocked("主机名无法解析") from exc
    addresses = {_canonical_ip(str(info[4][0])) for info in infos}
    addresses.discard(None)
    if not addresses:
        raise WebAccessBlocked("主机名没有可用地址")
    return addresses


def _guard_url(url: str) -> None:
    """出站前校验一个具体目标；每跳重定向都会再走一遍。"""
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise WebAccessBlocked("URL 端口不合法") from exc
    if parsed.scheme not in {"http", "https"}:
        raise WebAccessBlocked("仅支持 http/https")
    if parsed.username is not None or parsed.password is not None:
        raise WebAccessBlocked("URL 不允许携带账号密码")
    host = (parsed.hostname or "").strip().casefold()
    if not host:
        raise WebAccessBlocked("URL 缺少主机名")
    if host == "localhost" or host.endswith(_LOCAL_HOST_SUFFIXES):
        raise WebAccessBlocked(_BLOCK_HINT)
    literal = _canonical_ip(host)
    if literal is not None:
        if not _is_public_address(literal):
            raise WebAccessBlocked(_BLOCK_HINT)
        return
    default_port = 443 if parsed.scheme == "https" else 80
    for address in _resolve_addresses(host, port or default_port):
        # Fake-IP 例外只给 DNS 名：字面量在上面那一支已经判完了。
        if _is_proxy_fake_ip(address):
            continue
        if not _is_public_address(address):
            raise WebAccessBlocked(_BLOCK_HINT)


def _web_proxy() -> str | None:
    """外网工具专用代理;没配就返回 None(交回 httpx 的 trust_env 默认行为)。"""
    return os.environ.get(_PROXY_ENV, "").strip() or None


def _client() -> httpx2.Client:
    # follow_redirects=False 本身就是护栏的一部分:跟跳必须回 _guard_url 重判。
    #
    # 走代理**不放松 SSRF 护栏**:``_guard_url`` 判的是目标 URL 解析出来的地址,
    # 与走不走代理无关。代理自身是私网地址(172.17.0.1)也不受影响——它不是
    # 被校验的目标。Fake-IP 段的豁免见 ``_PROXY_FAKE_IP_NETWORKS``。
    return httpx2.Client(
        timeout=_TIMEOUT,
        follow_redirects=False,
        headers={"User-Agent": _UA},
        proxy=_web_proxy(),
    )


def _get_guarded(client: httpx2.Client, url: str) -> Any:
    """两个外网工具唯一的出站口：手动跟重定向，每跳先过 ``_guard_url``。

    为什么不用 httpx 的 event hooks（它确实每跳都触发）：hook 是 client 级配置，
    日后谁在别处 new 一个 client 就静默失去全部校验；钩子里抛异常还要依赖
    httpx 内部「先跑 hook 再发包」的顺序。手动跟把「跳数上限 + 每跳校验」摆在
    同一个函数里，读代码就能确认没有绕过路径，也顺带拦住
    ``302 Location: file:///…`` 这类换 scheme 的跳。
    """
    request = client.build_request("GET", url)
    for _ in range(_MAX_REDIRECTS + 1):
        # 校验 httpx 归一化后的 URL（IDN 已转 punycode），即它真正要拨的目标。
        _guard_url(str(request.url))
        response = client.send(request, follow_redirects=False)
        following = response.next_request
        if following is None:
            return response
        response.close()
        request = following
    raise WebAccessBlocked(f"重定向超过 {_MAX_REDIRECTS} 跳，已停止")


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = ""
        for key, value in attrs:
            if key.lower() == "href" and value:
                href = value
                break
        self._href = href
        self._buf = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        title = unescape("".join(self._buf)).strip()
        href = self._href
        self._href = ""
        self._buf = []
        if title and href:
            self.links.append((title, href))


def _unwrap_ddg(href: str) -> str:
    if "uddg=" in href:
        qs = parse_qs(urlparse(href).query)
        values = qs.get("uddg") or []
        if values:
            return unquote(values[0])
    return href


def _search_duckduckgo(query: str, *, limit: int) -> list[dict[str, str]]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    with _client() as client:
        response = _get_guarded(client, url)
        response.raise_for_status()
        html = response.text
    parser = _LinkCollector()
    parser.feed(html)
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for title, href in parser.links:
        if "duckduckgo.com" in href and "uddg=" not in href:
            continue
        target = _unwrap_ddg(href)
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"}:
            continue
        if target in seen:
            continue
        seen.add(target)
        out.append({"title": title[:200], "url": target, "snippet": ""})
        if len(out) >= limit:
            break
    return out


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        if tag.lower() in {"p", "br", "li", "h1", "h2", "h3", "tr"} and not self._skip:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if text:
            self._parts.append(text)

    def text(self) -> str:
        raw = " ".join(self._parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _fetch_readable(url: str, *, max_chars: int) -> dict[str, Any]:
    # 主机校验在 _get_guarded 里逐跳做，这里不再单独判原始 URL 一次：
    # 「只校验用户给的那一个 URL」正是本工具此前被重定向绕过的原因。
    with _client() as client:
        response = _get_guarded(client, url)
        response.raise_for_status()
        ctype = response.headers.get("content-type", "")
        if "html" not in ctype.lower() and "text" not in ctype.lower():
            raise ValueError(f"不支持的内容类型：{ctype or 'unknown'}")
        html = response.text
    extractor = _TextExtractor()
    extractor.feed(html)
    body = extractor.text()[:max_chars]
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = unescape(re.sub(r"\s+", " ", title_match.group(1))).strip() if title_match else ""
    return {"url": url, "title": title[:200], "text": body, "truncated": len(body) >= max_chars}


def web_specs(bus: Any) -> dict[str, ToolSpec]:
    """注册到 SystemToolBus；query/url 允许出现在参数中。"""

    def search(args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query") or "").strip()
        if not query:
            return _err("query 不能为空")
        limit = int(args.get("limit") or 5)
        limit = max(1, min(_MAX_RESULTS, limit))
        try:
            results = _search_duckduckgo(query, limit=limit)
        except WebAccessBlocked as exc:
            return _err(f"web_search 拒绝：{exc}")
        except Exception as exc:
            return _err(f"web_search 失败：{type(exc).__name__}: {exc}")
        payload = {
            "query": query,
            "source": "duckduckgo_html",
            "disclaimer": "外网证据 · 非账本/行情真值",
            "results": results,
        }
        return _ok(payload)

    def fetch(args: dict[str, Any]) -> ToolResult:
        url = str(args.get("url") or "").strip()
        if not url:
            return _err("url 不能为空")
        max_chars = int(args.get("max_chars") or _MAX_FETCH_CHARS)
        max_chars = max(500, min(_MAX_FETCH_CHARS, max_chars))
        try:
            page = _fetch_readable(url, max_chars=max_chars)
        except WebAccessBlocked as exc:
            return _err(f"web_fetch 拒绝：{exc}")
        except Exception as exc:
            return _err(f"web_fetch 失败：{type(exc).__name__}: {exc}")
        payload = {
            **page,
            "disclaimer": "外网证据 · 非账本/行情真值",
        }
        return _ok(payload)

    return {
        "web_search": ToolSpec(
            "web_search",
            "检索公开网页（标题/链接）；结果为外网证据，不可当作账本或行情真值。",
            _object(
                {
                    "query": {"type": "string", "minLength": 1, "maxLength": 240},
                    "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_RESULTS},
                },
                ["query"],
            ),
            False,
            search,
            allow_urls=True,
        ),
        "web_fetch": ToolSpec(
            "web_fetch",
            "抓取单个公开网页正文；仅公网地址，本机/内网/云元数据拒绝（含重定向后）。",
            _object(
                {
                    "url": {"type": "string", "minLength": 8, "maxLength": 2000},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": _MAX_FETCH_CHARS},
                },
                ["url"],
            ),
            False,
            fetch,
            allow_urls=True,
        ),
    }
