"""AkShare 股票能力目录 API：浏览、单测、一键批量探测、版本检查。

目录由本机实际安装的 AkShare 版本反射得到。浏览器只能测试目录内的
``stock_*`` 函数，不能把模块名或可调用对象直接交给服务端执行。
不再提供「上桌/启用」开关——目录即全部可用面。
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from src.market.application.akshare import (
    DEFAULT_BATCH_PAGE,
    MAX_BATCH_PROBE,
    check_akshare_version,
    installed_akshare_version,
    probe_stock_capabilities_batch,
    probe_stock_capability,
    ProbeCapacityError,
    ProbeWorkerStartError,
    discover_stock_capabilities,
    source_label,
)

MAX_PROBE_REQUEST_BYTES = 16 * 1024
TOOL_NAME_PATTERN = r"^stock_[a-z0-9_]+$"
MAX_BATCH_NAMES = 200


class _ProbeBodyLimitRoute(APIRoute):
    """在 Pydantic 解码前限制受控试跑的请求体。"""

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original_handler = super().get_route_handler()

        async def limited_handler(request: Request) -> Response:
            if request.method != "POST":
                return await original_handler(request)
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > MAX_PROBE_REQUEST_BYTES:
                        raise HTTPException(status_code=413, detail="probe request body is too large")
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail="invalid Content-Length header") from exc

            received = 0

            async def limited_receive() -> dict[str, Any]:
                nonlocal received
                message = await request.receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > MAX_PROBE_REQUEST_BYTES:
                        raise HTTPException(status_code=413, detail="probe request body is too large")
                return message

            return await original_handler(Request(request.scope, limited_receive))

        return limited_handler


class AkShareProbePayload(BaseModel):
    """单接口探测仅接受 JSON 参数，具体签名由受控目录校验。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    params: dict[str, Any] = Field(default_factory=dict)


class AkShareBatchProbePayload(BaseModel):
    """一键/续跑批量探测。不传 names 则按目录全量分页。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    names: list[Annotated[str, Field(max_length=128, pattern=TOOL_NAME_PATTERN)]] | None = Field(
        default=None, max_length=MAX_BATCH_NAMES
    )
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=DEFAULT_BATCH_PAGE, ge=1, le=MAX_BATCH_PROBE)


def _public_capability(item: dict[str, Any]) -> dict[str, Any]:
    """保留目录原始溯源字段，同时适配工作台展示字段。"""
    result = dict(item)
    source = str(item.get("source") or "")
    category = str(item.get("category") or "")
    result["provider"] = str(item.get("source_label") or source)
    result["provider_id"] = source
    result["category_label"] = str(item.get("category_label") or category)
    result["summary"] = str(item.get("doc") or "")
    result["sample_params"] = item.get("default_params") or {}
    result["mode"] = str(item.get("execution_mode") or "")
    param_docs = item.get("param_docs")
    result["param_docs"] = param_docs if isinstance(param_docs, dict) else {}
    result["returns"] = str(item.get("returns") or "")
    return result


def _source_counts(capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按上游来源统计接口数量；始终基于未过滤目录。"""
    counts = Counter(str(item.get("source") or "") for item in capabilities)
    return [
        {
            "id": source,
            "label": source_label(source),
            "count": count,
        }
        for source, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def _missing_dependency(exc: ImportError) -> HTTPException:
    """市场 API 不能反向依赖 app.legacy 的组装辅助函数。"""
    return HTTPException(
        status_code=503,
        detail=f"该能力所需的依赖未安装（{exc.name}）。请安装 akshare 后重试。",
    )


def _open_access() -> None:
    """组合根没注入写鉴权时的占位（脚本/测试直接建路由）。"""
    return None


def build_akshare_catalog_router(*, write_dependency=None) -> APIRouter:
    """构造 AkShare 运行时目录及受控探测接口。"""
    router = APIRouter(route_class=_ProbeBodyLimitRoute)
    # 试跑虽不写库，但会消耗第三方源配额，必须受组合根访问控制。
    write_guard = Depends(write_dependency or _open_access)

    @router.get("/api/market/akshare/catalog", tags=["market"])
    def akshare_catalog(
        q: str = Query(default="", max_length=128),
        category: str = Query(default="", max_length=64),
        source: str = Query(default="", max_length=64),
    ) -> dict[str, Any]:
        """返回当前环境可发现的股票接口，不依赖静态、易过期的清单。"""
        try:
            all_capabilities = discover_stock_capabilities()
        except ImportError as exc:
            raise _missing_dependency(exc) from exc

        capabilities = list(all_capabilities)
        needle = q.strip().casefold()
        category_filter = category.strip()
        source_filter = source.strip()
        if needle:
            capabilities = [
                item
                for item in capabilities
                if needle
                in " ".join(
                    str(item.get(key) or "")
                    for key in ("name", "module", "doc", "source", "category")
                ).casefold()
            ]
        if category_filter:
            capabilities = [
                item for item in capabilities if item.get("category") == category_filter
            ]
        if source_filter:
            capabilities = [
                item for item in capabilities if item.get("source") == source_filter
            ]
        categories = sorted(
            {
                str(item.get("category") or "其他")
                for item in all_capabilities
            }
        )
        return {
            "akshare_version": installed_akshare_version(),
            "capabilities": [_public_capability(item) for item in capabilities],
            "total": len(capabilities),
            "categories": categories,
            "sources": _source_counts(all_capabilities),
            "batch_probe_max": MAX_BATCH_PROBE,
        }

    @router.get("/api/market/akshare/sources", tags=["market"])
    def akshare_sources() -> dict[str, Any]:
        """只回「每个来源挂了多少接口」。"""
        try:
            all_capabilities = discover_stock_capabilities()
        except ImportError as exc:
            raise _missing_dependency(exc) from exc

        return {
            "akshare_version": installed_akshare_version(),
            "sources": _source_counts(all_capabilities),
            "total": len(all_capabilities),
        }

    @router.get("/api/market/akshare/version", tags=["market"])
    def akshare_version(fetch_latest: bool = Query(default=True)) -> dict[str, Any]:
        """本机 akshare 版本；默认联网核对 PyPI 是否有更新。"""
        try:
            return check_akshare_version(fetch_latest=fetch_latest)
        except ImportError as exc:
            raise _missing_dependency(exc) from exc

    @router.post("/api/market/akshare/catalog/{name}/probe", tags=["market"])
    def probe_akshare_catalog_item(
        payload: AkShareProbePayload,
        name: str = Path(max_length=128, pattern=r"^stock_[a-z0-9_]+$"),
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """运行目录内单项的受控样例探测；不写入 market.db。"""
        try:
            return probe_stock_capability(name, payload.params)
        except ImportError as exc:
            raise _missing_dependency(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ProbeCapacityError as exc:
            raise HTTPException(
                status_code=429,
                detail="AkShare probe capacity is exhausted; retry later",
                headers={"Retry-After": "2"},
            ) from exc
        except ProbeWorkerStartError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/api/market/akshare/catalog/probe-batch", tags=["market"])
    def probe_akshare_catalog_batch(
        payload: AkShareBatchProbePayload,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """一键/分页批量探测目录接口可用性（不入库）。"""
        try:
            return probe_stock_capabilities_batch(
                names=payload.names,
                offset=payload.offset,
                limit=payload.limit,
            )
        except ImportError as exc:
            raise _missing_dependency(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
