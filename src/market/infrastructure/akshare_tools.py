"""AkShare 接口目录辅助：反射缓存、批量可用性探测、版本检查。

不再维护「上桌/启用」名单——目录里能反射到的 ``stock_*`` 一律可浏览、可试跑；
MCP 侧用单一 ``akshare_call`` 按名调用，避免把四百多个接口塞进工具清单。
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from collections.abc import Mapping

from src.market.infrastructure.akshare_catalog import (
    CatalogSource,
    discover_stock_capabilities,
    probe_stock_capability,
)
from src.market.infrastructure.akshare_probe_result import JsonValue
from src.market.infrastructure.akshare_probe_worker import (
    ProbeCapacityError,
    ProbeWorkerStartError,
)

LOGGER = logging.getLogger(__name__)

#: 一键全测单次请求最多跑多少个（防请求拖死进程；前端可分页续跑）。
MAX_BATCH_PROBE = 80
#: 前端实时进度建议每页条数（仍受 MAX_BATCH_PROBE 上限）。
DEFAULT_BATCH_PAGE = 5
#: 批量探测时每个接口的超时（秒），比 UI 单测略紧。
BATCH_PROBE_SECONDS = 6.0
#: 失败后自动重试一次（消化瞬时限流 / 偶发超时）。
BATCH_PROBE_RETRIES = 1
#: PyPI 版本查询超时。
PYPI_TIMEOUT_SECONDS = 5.0

_CATALOG_CACHE: list[dict[str, JsonValue]] | None = None


def catalog_entries(
    resolver: CatalogSource | None = None,
) -> list[dict[str, JsonValue]]:
    """本机目录。同一进程里 akshare 版本不会变，反射一次就够。"""
    global _CATALOG_CACHE
    if resolver is not None:
        return discover_stock_capabilities(resolver)
    if _CATALOG_CACHE is None:
        _CATALOG_CACHE = discover_stock_capabilities()
    return _CATALOG_CACHE


def clear_catalog_cache() -> None:
    """测试与「换了 akshare 版本」时用；正常运行期不需要调。"""
    global _CATALOG_CACHE
    _CATALOG_CACHE = None


def installed_akshare_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("akshare")
    except PackageNotFoundError:
        return ""


def check_akshare_version(*, fetch_latest: bool = True) -> dict[str, JsonValue]:
    """本机安装版本 vs PyPI 最新（可选联网）。

    不写配置、不入库；失败只报 ``error``，不伪装成已是最新。
    """
    installed = installed_akshare_version()
    result: dict[str, JsonValue] = {
        "installed": installed,
        "latest": None,
        "update_available": False,
        "pypi_url": "https://pypi.org/pypi/akshare/json",
        "error": None,
    }
    if not fetch_latest:
        return result
    try:
        latest = _fetch_pypi_latest()
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    result["latest"] = latest
    if installed and latest and installed != latest:
        result["update_available"] = True
    return result


def _fetch_pypi_latest() -> str:
    request = urllib.request.Request(
        "https://pypi.org/pypi/akshare/json",
        headers={"Accept": "application/json", "User-Agent": "loci-akshare-version-check"},
    )
    with urllib.request.urlopen(request, timeout=PYPI_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    info = payload.get("info") if isinstance(payload, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError("PyPI response missing info.version")
    return version.strip()


def probe_stock_capabilities_batch(
    *,
    names: list[str] | None = None,
    offset: int = 0,
    limit: int = DEFAULT_BATCH_PAGE,
    resolver: CatalogSource | None = None,
) -> dict[str, JsonValue]:
    """按目录顺序批量受控探测；返回本页结果 + 续跑游标。

    默认参数走目录里的 sample；单个失败记入 ``results``，不中断整批。
    并发仍受探针槽限制——这里串行调用，避免把自己打成 429。
    """
    entries = catalog_entries(resolver)
    by_name = {str(item.get("name") or ""): item for item in entries}
    if names:
        ordered = [name for name in names if name in by_name]
        missing = [name for name in names if name not in by_name]
    else:
        ordered = [str(item.get("name") or "") for item in entries if item.get("name")]
        missing = []

    start = max(0, int(offset))
    page_size = max(1, min(int(limit), MAX_BATCH_PROBE))
    page = ordered[start : start + page_size]
    results: list[dict[str, JsonValue]] = []
    ok = 0
    failed = 0
    skipped = 0

    for name in page:
        item = by_name.get(name) or {}
        status = str(item.get("status") or "")
        params = item.get("default_params")
        sample = params if isinstance(params, dict) else {}

        # 缺必填样例的接口直接跳过，不算失败——硬跑只会刷一屏参数错误。
        if status == "needs_parameters":
            required = [
                str(p.get("name") or "")
                for p in (item.get("parameters") or [])
                if isinstance(p, dict) and p.get("required")
            ]
            missing_required = [key for key in required if key and key not in sample]
            if missing_required:
                skipped += 1
                results.append(
                    {
                        "name": name,
                        "ok": False,
                        "skipped": True,
                        "error": f"缺少必填样例参数：{', '.join(missing_required)}",
                        "elapsed_ms": None,
                        "rows": None,
                    }
                )
                continue

        outcome, attempts = _probe_with_retry(name, sample, resolver=resolver)
        if outcome is None:
            failed += 1
            results.append(
                {
                    "name": name,
                    "ok": False,
                    "skipped": False,
                    "error": "probe returned no result",
                    "elapsed_ms": None,
                    "rows": None,
                    "attempts": attempts,
                }
            )
            continue

        error = outcome.get("error")
        is_ok = not error
        if is_ok:
            ok += 1
        else:
            failed += 1
        results.append(
            {
                "name": name,
                "ok": is_ok,
                "skipped": False,
                "error": error,
                "elapsed_ms": outcome.get("elapsed_ms"),
                "rows": outcome.get("rows"),
                "attempts": attempts,
            }
        )

    next_offset = start + len(page)
    return {
        "results": results,
        "ok": ok,
        "failed": failed,
        "skipped": skipped,
        "missing": missing,
        "offset": start,
        "limit": page_size,
        "next_offset": next_offset if next_offset < len(ordered) else None,
        "total_targets": len(ordered),
        "done": next_offset >= len(ordered),
    }


def _probe_with_retry(
    name: str,
    sample: Mapping[str, JsonValue],
    *,
    resolver: CatalogSource | None,
) -> tuple[dict[str, JsonValue] | None, int]:
    """受控探测；瞬时失败再试一次。返回 (结果, 尝试次数)。"""
    attempts = 0
    last: dict[str, JsonValue] | None = None
    for attempt in range(BATCH_PROBE_RETRIES + 1):
        attempts = attempt + 1
        try:
            last = probe_stock_capability(name, dict(sample), resolver=resolver)
        except (ProbeCapacityError, ProbeWorkerStartError) as exc:
            last = {
                "error": str(exc),
                "elapsed_ms": None,
                "rows": None,
            }
            break
        except ValueError as exc:
            return {"error": str(exc), "elapsed_ms": None, "rows": None}, attempts
        except Exception as exc:
            last = {
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_ms": None,
                "rows": None,
            }
            if attempt < BATCH_PROBE_RETRIES:
                time.sleep(0.4)
                continue
            break
        if not last.get("error"):
            return last, attempts
        if attempt < BATCH_PROBE_RETRIES:
            time.sleep(0.4)
            continue
        break
    return last, attempts
