"""战法定时选股绑定上的可复用配置（股票池等）。"""
from __future__ import annotations

from typing import Any


def load_screen_job_universe(slug: str, *, store: Any | None = None) -> dict[str, Any] | None:
    """读取 ``screen:{slug}`` 任务里保存的行情范围；无绑定或未配置则 None。"""
    plain = str(slug or "").strip()
    if not plain:
        return None

    def _read(ops: Any) -> dict[str, Any] | None:
        job = ops.get_job_by_name(f"screen:{plain}")
        if not isinstance(job, dict):
            return None
        cfg = job.get("config")
        if not isinstance(cfg, dict):
            return None
        universe = cfg.get("universe")
        return dict(universe) if isinstance(universe, dict) else None

    if store is not None:
        return _read(store)
    from src.ops import OpsStore

    with OpsStore() as ops:
        return _read(ops)


def resolve_screen_universe(
    slug: str,
    requested: dict[str, Any] | None,
    *,
    store: Any | None = None,
) -> dict[str, Any] | None:
    """请求显式传入优先；否则回落定时任务保存的行情范围。"""
    if isinstance(requested, dict):
        return requested
    return load_screen_job_universe(slug, store=store)
