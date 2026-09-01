"""租户上下文：把「当前请求属于哪个用户」变成进程内可查询的事实。

设计要点（为什么是 ContextVar 而不是到处传参）：

- 仓内 25+ 个 router 工厂在 ``create_app`` 时一次性构建，形参 ``palace_db`` /
  ``ops_db`` 在那一刻就被闭包捕获。真要「每请求换库」，逐个改工厂签名会波及
  上百个调用点，且每加一个上下文就要再改一遍。
- 但这些工厂默认收到的是 ``None``（见 ``src/app/main.py`` 的 include_router），
  下游 ``OpsStore(None)`` / ``MarketStore(None)`` 会惰性回落到
  ``src.shared.paths`` 的解析函数。于是只要让那几个解析函数认得当前租户，
  多租户就自动生效，且不动任何业务代码。
- ContextVar 天然随 asyncio Task 传播；FastAPI 的同步路由跑在 threadpool，
  Starlette 会把上下文 copy 过去，因此同步路由同样读得到。

隔离边界（谁分库、谁共享）：

- ``palace.db`` 账本：每租户。成交/候选/预案/复盘是私人事实。
- ``ops.db`` 运维：每租户。LLM 密钥、AI 会话、纸面舱、任务配置都是私密的。
- ``skills/`` ``research_runs/``：每租户。用户自建战法与研究产物。
- ``market.db`` ``market_hot.db``：全局共享。行情是公共事实，按人复制既费磁盘又费带宽。
- ``identity.db`` ``community.db``：全局共享。身份与社区本来就是跨用户的。

主租户（primary tenant）就是老的 ``data/`` 目录本身：升级到 v2 的存量单机用户
以管理员身份登录后看到的还是原来那套库，零迁移。新注册用户落在
``data/tenants/<user_id>/``。
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import Context, ContextVar, Token, copy_context
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re
import threading

#: 主租户哨兵：解析路径时等价于「不分库，直接用 data/ 根」。
PRIMARY_TENANT = "__primary__"

#: 后台系统任务（行情同步等）使用的租户；与主租户同一套库。
SYSTEM_TENANT = PRIMARY_TENANT

#: 租户目录名允许的字符；用户 id 由服务端生成，这里是纵深防御，
#: 防止任何一天有人把用户输入直接塞进来做路径拼接。
_SAFE_TENANT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: 「没人绑过」的哨兵。**不能直接拿 PRIMARY_TENANT 当默认值**——那样
#: 「后台线程丢了上下文」与「本来就是主租户」长得一模一样，而前者是必须
#: 报错的 bug、后者是正常路径。current_tenant() 对外仍把哨兵映射成主租户
#: （存量单机零迁移），只有 require_tenant() 看得见区别。
_UNBOUND = "\x00unbound"

_current_tenant: ContextVar[str] = ContextVar("loci_current_tenant", default=_UNBOUND)


class TenantError(ValueError):
    """租户标识非法。"""


def normalize_tenant(tenant_id: str | None) -> str:
    """空值归一到主租户；非法字符直接拒绝，不做「尽力清洗」。"""
    raw = (tenant_id or "").strip()
    if not raw or raw == PRIMARY_TENANT:
        return PRIMARY_TENANT
    if not _SAFE_TENANT.match(raw):
        raise TenantError(f"非法租户标识：{raw!r}")
    return raw


def current_tenant() -> str:
    """当前租户；没人绑过时回落主租户（桌面单机、CLI、启动期都走这条）。"""
    value = _current_tenant.get()
    return PRIMARY_TENANT if value == _UNBOUND else value


def is_primary_tenant(tenant_id: str | None = None) -> bool:
    candidate = tenant_id if tenant_id is not None else current_tenant()
    return normalize_tenant(candidate) == PRIMARY_TENANT


def set_current_tenant(tenant_id: str | None) -> Token[str]:
    """绑定当前租户，返回可用于 ``reset`` 的 token。"""
    return _current_tenant.set(normalize_tenant(tenant_id))


def reset_current_tenant(token: Token[str]) -> None:
    _current_tenant.reset(token)


@contextmanager
def tenant_scope(tenant_id: str | None) -> Iterator[str]:
    """``with tenant_scope(uid):`` —— 后台任务/CLI 显式切租户用这个。"""
    token = set_current_tenant(tenant_id)
    try:
        yield current_tenant()
    finally:
        reset_current_tenant(token)


@dataclass(frozen=True, slots=True)
class TenantPaths:
    """一个租户的全部私有路径。行情库不在其中——那是全局的。"""

    tenant_id: str
    root: Path
    palace_db: Path
    ops_db: Path
    skill_root: Path
    skill_runs_dir: Path
    research_runs_dir: Path
    mcp_json: Path

    @property
    def is_primary(self) -> bool:
        return self.tenant_id == PRIMARY_TENANT


def tenant_root(data_root: Path, tenant_id: str | None = None) -> Path:
    """租户私有目录。主租户即 ``data/`` 本身（存量用户零迁移）。"""
    candidate = tenant_id if tenant_id is not None else current_tenant()
    resolved = normalize_tenant(candidate)
    if resolved == PRIMARY_TENANT:
        return data_root
    return data_root / "tenants" / resolved


def tenant_paths(data_root: Path, tenant_id: str | None = None) -> TenantPaths:
    candidate = tenant_id if tenant_id is not None else current_tenant()
    resolved = normalize_tenant(candidate)
    root = tenant_root(data_root, resolved)
    return TenantPaths(
        tenant_id=resolved,
        root=root,
 palace_db=root / "palace.db",
        ops_db=root / "ops.db",
        skill_root=root / "skills",
  skill_runs_dir=root / "skill_runs",
        research_runs_dir=root / "research_runs",
   mcp_json=root / "mcp.json",
    )


def ensure_tenant_root(data_root: Path, tenant_id: str | None = None) -> Path:
    """创建租户目录树。不建空库——各 Store 首次打开时自己会建 schema。"""
    paths = tenant_paths(data_root, tenant_id)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.skill_root.mkdir(parents=True, exist_ok=True)
    return paths.root


def list_tenant_ids(data_root: Path) -> list[str]:
    """磁盘上已经存在的非主租户目录。用于运维盘点，不作为权威用户名单。"""
    base = data_root / "tenants"
    if not base.is_dir():
        return []
    out: list[str] = []
    for child in sorted(base.iterdir()):
        if child.is_dir() and _SAFE_TENANT.match(child.name):
            out.append(child.name)
    return out


#: 线程/线程池入口的租户传播工具。
#:
#: **`ContextVar` 不跨 `threading.Thread` 与 `ThreadPoolExecutor` 边界。**
#: 只有 asyncio Task 与 anyio 的 `run_in_threadpool` 会自动复制 Context。
#: 从请求里裸起一条线程，线程内 `current_tenant()` 直接落回 `PRIMARY_TENANT`
#: 默认值——也就是**管理员的老 data/ 目录**。这个 bug 不报错、不刷红，
#: 只是把 B 用户的选股结果静默写进管理员的账本，单机形态下 100% 观察不到。
#:
#: 因此：**后台线程一律经这两个包装器起**，禁止直接 `threading.Thread(...)`
#: 或 `executor.submit(...)`。


def copy_tenant_context() -> Context:
    """当前上下文的快照。给需要自己管线程的调用方用。"""
    return copy_context()


def spawn_tenant_thread(
    target: Callable[..., Any],
    *,
    name: str | None = None,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    daemon: bool = True,
    start: bool = True,
) -> threading.Thread:
    """起一条**带着当前租户**的后台线程。

        等价于 ``threading.Thread(target=...)``，但线程体跑在调用时刻的 Context
        副本里，于是 ``current_tenant()`` / ``palace_db()`` / ``ops_db()`` 在线程
        内解析出的仍是发起请求那个用户的库。

        ``Context.run`` 只能进入一次，所以返回的 Thread 也只能 start 一次——
        一次性后台线程本来就没人会 restart。
        """
    context = copy_context()
    payload = dict(kwargs or {})

    def _entry() -> None:
        context.run(target, *args, **payload)

    thread = threading.Thread(target=_entry, name=name, daemon=daemon)
    if start:
        thread.start()
    return thread


def submit_with_tenant(executor: Any, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """``executor.submit`` 的租户安全版本。

        ``ThreadPoolExecutor`` 的工作线程是复用的，它们的 Context 是线程创建那一
        刻的快照——与提交任务的那个请求毫无关系。必须显式带过去。
        """
    context = copy_context()
    return executor.submit(context.run, fn, *args, **kwargs)


def tenant_is_bound() -> bool:
    """当前上下文是否**显式**绑过租户（而不是吃了默认值）。"""
    return _current_tenant.get() != _UNBOUND


def require_tenant() -> str:
    """拿当前租户，**未显式绑定就抛异常**。

        ``current_tenant()`` 的默认值是主租户，这让存量单机零迁移，但也意味着任何
        丢了上下文的路径都会静默降级成管理员身份。在「一定是某个具体用户发起的」
        场合（后台线程体、跨租户批处理）用这个，把静默串味变成显式失败。
        """
    value = _current_tenant.get()
    if value == _UNBOUND:
        raise TenantError("当前上下文没有绑定租户（后台线程忘了用 spawn_tenant_thread？）")
    return normalize_tenant(value)
