"""AkShare 目录与受控探测用例的公开入口。"""
from __future__ import annotations

from typing import Any

from src.market.infrastructure.akshare_probe_worker import (
    ProbeCapacityError,
    ProbeWorkerStartError,
)
from src.market.infrastructure.akshare_tools import DEFAULT_BATCH_PAGE, MAX_BATCH_PROBE


def discover_stock_capabilities() -> list[dict[str, Any]]:
    """本机 AkShare 目录（读路径）。

    走 ``catalog_entries()`` 的进程内缓存：同一进程里 akshare 版本不会变，
    ``vars(akshare)`` 全量反射一次就够，别让每个 GET 请求重做四百次
    ``inspect.signature`` / docstring 解析。换了 akshare 版本用既有的
    ``clear_catalog_cache()`` 失效，不另造机制。
    """
    from src.market.infrastructure.akshare_tools import catalog_entries

    return catalog_entries()


def probe_stock_capability(name: str, params: dict[str, Any]) -> dict[str, Any]:
    from src.market.infrastructure.akshare_catalog import (
        probe_stock_capability as _probe_stock_capability,
    )

    return _probe_stock_capability(name, params)


def source_label(source: str) -> str:
    from src.market.infrastructure.akshare_catalog_meta import source_label as _source_label

    return _source_label(source)


def installed_akshare_version() -> str:
    from src.market.infrastructure.akshare_tools import (
        installed_akshare_version as _installed_akshare_version,
    )

    return _installed_akshare_version()


def check_akshare_version(*, fetch_latest: bool = True) -> dict[str, Any]:
    from src.market.infrastructure.akshare_tools import (
        check_akshare_version as _check_akshare_version,
    )

    return _check_akshare_version(fetch_latest=fetch_latest)


def probe_stock_capabilities_batch(
    *,
    names: list[str] | None = None,
    offset: int = 0,
    limit: int = DEFAULT_BATCH_PAGE,
) -> dict[str, Any]:
    from src.market.infrastructure.akshare_tools import (
        probe_stock_capabilities_batch as _probe_stock_capabilities_batch,
    )

    return _probe_stock_capabilities_batch(names=names, offset=offset, limit=limit)


__all__ = [
    "MAX_BATCH_PROBE",
    "DEFAULT_BATCH_PAGE",
    "ProbeCapacityError",
    "ProbeWorkerStartError",
    "check_akshare_version",
    "discover_stock_capabilities",
    "installed_akshare_version",
    "probe_stock_capabilities_batch",
    "probe_stock_capability",
    "source_label",
]
