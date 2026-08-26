"""统一战法目录：builtin + screen skill。"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.strategy.domain.base import StrategyEngine, StrategyError, StrategyInfo, _REGISTRY
from src.strategy.application import (  # noqa: F401
    qianlong,
    tail_resonance,
    yangshi_tail,
)

_SCREEN_ENGINES: dict[str, StrategyEngine] = {}
_SCREEN_METADATA: dict[str, dict[str, Any]] = {}


def replace_screen_engines(
    engines: list[StrategyEngine],
    *,
    metadata_by_slug: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    builtins = set(_REGISTRY)
    next_map: dict[str, StrategyEngine] = {}
    for engine in engines:
        if engine.slug in builtins:
            raise StrategyError(f"策略 slug 重复：{engine.slug}")
        if engine.slug in next_map:
            raise StrategyError(f"策略 slug 重复：{engine.slug}")
        next_map[engine.slug] = engine
    _SCREEN_ENGINES.clear()
    _SCREEN_ENGINES.update(next_map)
    _SCREEN_METADATA.clear()
    for slug, metadata in (metadata_by_slug or {}).items():
        if slug in next_map:
            _SCREEN_METADATA[slug] = dict(metadata)


def get(slug: str) -> StrategyEngine:
    if slug in _REGISTRY:
        return _REGISTRY[slug]
    if slug in _SCREEN_ENGINES:
        return _SCREEN_ENGINES[slug]
    raise StrategyError(
        f"未注册的策略：{slug}（已注册：{sorted([*_REGISTRY, *_SCREEN_ENGINES])}）"
    )


def all_strategies() -> list[StrategyEngine]:
    merged = {**_REGISTRY, **_SCREEN_ENGINES}
    return [merged[slug] for slug in sorted(merged)]


def describe_all(
    *, metadata_by_slug: Mapping[str, Mapping[str, Any]] | None = None
) -> list[StrategyInfo]:
    """统一目录；内置静态元数据原样透传，持久化自定义策略可叠加运行元数据。"""
    described: list[StrategyInfo] = []
    for engine in all_strategies():
        revision = str(getattr(engine, "strategy_revision", f"builtin:{engine.slug}"))
        screen_metadata = _SCREEN_METADATA.get(engine.slug, {})
        static_version = str(screen_metadata.get("version") or getattr(engine, "version", revision))
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
