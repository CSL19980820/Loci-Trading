"""统一战法目录：builtin + screen skill。

**为什么必须按租户分片**（详见 ``src/strategy/README.md``「战法目录的租户分片」）：
内置战法（``_REGISTRY``）是代码事实，全进程共享一份没问题；Screen Skill 却是从
**用户私有目录**（``skill_root()`` 随 ``current_tenant()`` 走）编译出来的引擎。
历史实现把它们塞进一个进程级 dict，刷新还是 ``clear()+update()`` 全量替换，于是
A 一保存战法，B 的战法当场消失，同时 B 看到 A 的私有战法；而 ``get(slug)`` 被
``screener`` 与 ``backtest/runner`` 直接消费，等于 B 能跑 A 的代码，引擎的
``install_path`` 还指着 A 的租户目录。

所以引擎与元数据都按 ``current_tenant()`` 分片，且分片是**惰性**的：进程启动时
只刷过主租户，别的租户首次访问才通过 ``set_loader`` 注入的回调加载（catalog 不能
反向 import ``screen_skills``——那边已经 import 了 catalog，会成环）。分片总数有
LRU 上限，避免几十个租户的已编译引擎常驻内存。
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
import threading
from typing import Any, Callable

from src.shared.tenancy import current_tenant
from src.strategy.domain.base import StrategyEngine, StrategyError, StrategyInfo, _REGISTRY
from src.strategy.application import (  # noqa: F401
    qianlong,
    tail_resonance,
    yangshi_tail,
)

logger = logging.getLogger(__name__)

#: 常驻内存的租户分片上限（LRU）。已编译的 Python Screen Skill 是活模块对象加闭包，
#: 几十个租户各留一份能吃掉几百 MB，而服务器只有 1.1G。被淘汰的租户下次访问会重新
#: 惰性加载，语义不变，只是慢一点。
MAX_TENANT_SHARDS = 64


@dataclass
class _Shard:
    """一个租户的 screen 引擎视图。``loaded`` 表示已经从磁盘刷过一次。"""

    engines: dict[str, StrategyEngine] = field(default_factory=dict)
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    loaded: bool = False


_LOCK = threading.RLock()
#: LRU：最近使用的排在末尾。
_SHARDS: "OrderedDict[str, _Shard]" = OrderedDict()

#: 惰性加载的串行化锁。只保护「加载」这件事，不保护读——磁盘 IO 与包编译不能把
#: 所有租户的目录读操作一起堵住。
_LOAD_LOCK = threading.RLock()
#: 正在加载的租户。loader 内部会回调 ``replace_screen_engines``，靠它防重入。
_LOADING: set[str] = set()
_LOADER: Callable[[], Any] | None = None


def set_loader(loader: Callable[[], Any] | None) -> None:
    """注册「把当前租户的 Screen Skill 刷进目录」的回调。

    由 ``screen_skills`` 在 import 期注册 ``refresh_screen_strategy_catalog``。
    没注册时目录退化成「只有显式 ``replace_screen_engines`` 灌进来的东西」，
    也就是改造前的行为，纯 CLI / 单测路径不受影响。
    """
    global _LOADER
    with _LOCK:
        _LOADER = loader


def _evict_locked() -> None:
    while len(_SHARDS) > MAX_TENANT_SHARDS:
        victim, _dropped = _SHARDS.popitem(last=False)
        logger.debug("战法目录分片超上限，淘汰租户 %s（下次访问重新加载）", victim)


def _shard_locked(tenant: str) -> _Shard:
    shard = _SHARDS.get(tenant)
    if shard is None:
        shard = _Shard()
        _SHARDS[tenant] = shard
        _evict_locked()
    else:
        _SHARDS.move_to_end(tenant)
    return shard


def _ensure_loaded(tenant: str) -> None:
    """租户首次被访问时，从它自己的 ``skill_root()`` 刷一次目录。"""
    with _LOCK:
        shard = _shard_locked(tenant)
        if shard.loaded or tenant in _LOADING or _LOADER is None:
            return
        loader = _LOADER
    with _LOAD_LOCK:
        with _LOCK:
            shard = _shard_locked(tenant)
            if shard.loaded or tenant in _LOADING:
                return
            _LOADING.add(tenant)
        try:
            loader()
        except Exception:
            # 目录加载失败不能让战法列表/选股整个 500：按空目录处理并留日志；
            # 任何一次保存/更新战法都会显式重刷，届时自愈。
            logger.exception("加载租户 %s 的战法目录失败（按空目录处理）", tenant)
        finally:
            with _LOCK:
                _LOADING.discard(tenant)
                _shard_locked(tenant).loaded = True


def _view() -> tuple[dict[str, StrategyEngine], dict[str, dict[str, Any]]]:
    """当前租户的 (引擎, 元数据) 浅拷贝。"""
    tenant = current_tenant()
    _ensure_loaded(tenant)
    with _LOCK:
        shard = _shard_locked(tenant)
        return dict(shard.engines), dict(shard.metadata)


def replace_screen_engines(
    engines: list[StrategyEngine],
    *,
    metadata_by_slug: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    """全量替换**当前租户**的分片。别的租户一根毫毛都不许动。"""
    builtins = set(_REGISTRY)
    next_map: dict[str, StrategyEngine] = {}
    for engine in engines:
        if engine.slug in builtins:
            raise StrategyError(f"策略 slug 重复：{engine.slug}")
        if engine.slug in next_map:
            raise StrategyError(f"策略 slug 重复：{engine.slug}")
        next_map[engine.slug] = engine
    next_metadata: dict[str, dict[str, Any]] = {}
    for slug, metadata in (metadata_by_slug or {}).items():
        if slug in next_map:
            next_metadata[slug] = dict(metadata)
    with _LOCK:
        shard = _shard_locked(current_tenant())
        shard.engines = next_map
        shard.metadata = next_metadata
        # 显式刷过就算加载过，否则下一次读会再触发惰性加载把这次结果盖掉。
        shard.loaded = True


def get(slug: str) -> StrategyEngine:
    if slug in _REGISTRY:
        return _REGISTRY[slug]
    engines, _metadata = _view()
    if slug in engines:
        return engines[slug]
    raise StrategyError(
        f"未注册的策略：{slug}（已注册：{sorted([*_REGISTRY, *engines])}）"
    )


def all_strategies() -> list[StrategyEngine]:
    engines, _metadata = _view()
    merged = {**_REGISTRY, **engines}
    return [merged[slug] for slug in sorted(merged)]


def screen_catalog_stats() -> dict[str, Any]:
    """分片盘点。给运维与回归测试看，不进 HTTP 响应。"""
    with _LOCK:
        return {
            "tenants": len(_SHARDS),
            "max_tenants": MAX_TENANT_SHARDS,
            "engines": {tenant: len(shard.engines) for tenant, shard in _SHARDS.items()},
            "loader": _LOADER is not None,
        }


def snapshot_screen_state() -> dict[str, Any]:
    """整张分片表的快照。**仅供测试隔离**（见 ``tests/conftest.py``）。"""
    with _LOCK:
        return {
            tenant: (dict(shard.engines), dict(shard.metadata), shard.loaded)
            for tenant, shard in _SHARDS.items()
        }


def restore_screen_state(state: Mapping[str, Any] | None) -> None:
    """还原 ``snapshot_screen_state`` 的快照。**仅供测试隔离**。"""
    with _LOCK:
        _SHARDS.clear()
        for tenant, payload in dict(state or {}).items():
            engines, metadata, loaded = payload
            _SHARDS[tenant] = _Shard(
                engines=dict(engines),
                metadata=dict(metadata),
                loaded=bool(loaded),
            )
        _evict_locked()


def describe_all(
    *, metadata_by_slug: Mapping[str, Mapping[str, Any]] | None = None
) -> list[StrategyInfo]:
    """统一目录；内置静态元数据原样透传，持久化自定义策略可叠加运行元数据。"""
    described: list[StrategyInfo] = []
    screen_engines, screen_metadata_all = _view()
    merged = {**_REGISTRY, **screen_engines}
    for slug in sorted(merged):
        engine = merged[slug]
        revision = str(getattr(engine, "strategy_revision", f"builtin:{engine.slug}"))
        screen_metadata = screen_metadata_all.get(engine.slug, {})
        static_version = str(
            screen_metadata.get("version") or getattr(engine, "version", revision)
        )
        source_kind = str(getattr(engine, "source_kind", "builtin"))
        stored_metadata = metadata_by_slug.get(engine.slug, {}) if metadata_by_slug else {}
        metadata = (
            stored_metadata
            if metadata_by_slug and source_kind != "builtin"
            else {}
        )
        history = metadata.get("version_history") or screen_metadata.get(
            "version_history", getattr(engine, "version_history", [])
        )
        metrics = metadata.get(
            "backtest_metrics",
            screen_metadata.get("backtest_metrics", getattr(engine, "backtest_metrics", None)),
        )
        config = metadata.get(
            "backtest_config",
            screen_metadata.get("backtest_config", getattr(engine, "backtest_config", None)),
        )
        described.append(
            {
                "slug": engine.slug,
                "name": engine.name,
                "description": engine.description,
                "entry_instructions": str(
                    stored_metadata.get("entry_instructions")
                    or getattr(engine, "entry_instructions", "")
                ),
                "entry_timing": engine.entry_timing,
                "required_fields": list(engine.required_fields()),
                "min_bars": engine.min_bars(),
                "params": engine.default_params(),
                "default_universe": getattr(engine, "default_universe", None),
                "source_kind": source_kind,
                "runtime": getattr(engine, "runtime", None),
                "dialect": getattr(engine, "dialect", None),
                "entrypoint": getattr(engine, "entrypoint", None),
                "editable": bool(getattr(engine, "editable", False)),
                "strategy_revision": revision,
                "version": str(metadata.get("version") or static_version),
                "version_history": history if isinstance(history, list) else [],
                "backtest_metrics": metrics if isinstance(metrics, dict) else None,
                "backtest_config": config if isinstance(config, dict) else None,
            }
        )
    return described
