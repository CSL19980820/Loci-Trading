"""AkShare 目录 HTTP 契约：仅反射受控的股票函数，不执行真实网络。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from src.app.main import create_app
from src.market.api.akshare import MAX_PROBE_REQUEST_BYTES, build_akshare_catalog_router
from src.market.infrastructure.akshare_tools import DEFAULT_BATCH_PAGE
from src.market.infrastructure.akshare_probe_worker import (
    ProbeCapacityError,
    ProbeWorkerStartError,
)


def _catalog_fixture() -> list[dict[str, object]]:
    return [
        {
            "name": "stock_zh_a_hist",
            "module": "akshare.stock_feature.stock_hist_em",
            "signature": "(symbol='000001', period='daily')",
            "doc": "A 股历史行情",
            "param_docs": {"symbol": "股票代码", "period": "周期"},
            "returns": "每日行情数据",
            "source": "东方财富",
            "category": "历史行情",
            "default_params": {"symbol": "000001", "period": "daily"},
            "parameters": [
                {
                    "name": "symbol",
                    "required": True,
                    "kind": "text",
                    "annotation": "str",
                    "has_default": False,
                    "default": None,
                    "sample": "000001",
                }
            ],
            "execution_mode": "batch_cache_only",
            "status": "available",
        },
        {
            "name": "stock_zh_a_spot_em",
            "module": "akshare.stock_feature.stock_zh_a_sina",
            "signature": "()",
            "doc": "A 股实时行情",
            "source": "新浪",
            "category": "实时行情",
            "default_params": {},
            "parameters": [],
            "execution_mode": "on_demand",
            "status": "available",
        },
        {
            "name": "stock_individual_fund_flow",
            "module": "akshare.stock_feature.stock_fund_flow",
            "signature": "(stock='600519')",
            "doc": "个股资金流",
            "source": "东方财富",
            "category": "资金流",
            "default_params": {"stock": "600519"},
            "parameters": [],
            "execution_mode": "on_demand",
            "status": "available",
        },
    ]


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "palace.db", tmp_path / "no-static"))


@pytest.fixture(autouse=True)
def _isolate_catalog_cache():
    from src.market.infrastructure.akshare_tools import clear_catalog_cache

    clear_catalog_cache()
    yield
    clear_catalog_cache()


def test_catalog_exposes_runtime_metadata_and_display_aliases(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with patch(
            "src.market.infrastructure.akshare_tools.discover_stock_capabilities",
            return_value=_catalog_fixture(),
        ):
            response = client.get("/api/market/akshare/catalog?q=hist")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert "enabled_names" not in body
    assert "enabled_max" not in body
    assert body["batch_probe_max"] >= 1
    item = body["capabilities"][0]
    assert item["name"] == "stock_zh_a_hist"
    assert item["provider"] == "东方财富"
    assert item["provider_id"] == "东方财富"
    assert item["category_label"] == "历史行情"
    assert item["summary"] == "A 股历史行情"
    assert item["sample_params"]["symbol"] == "000001"
    assert item["mode"] == "batch_cache_only"
    assert item["parameters"][0]["required"] is True
    assert item["param_docs"] == {"symbol": "股票代码", "period": "周期"}
    assert "enabled" not in item
    assert item["returns"] == "每日行情数据"


def test_catalog_defaults_missing_doc_sections_for_older_catalog_entries(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with patch(
            "src.market.infrastructure.akshare_tools.discover_stock_capabilities",
            return_value=_catalog_fixture(),
        ):
            response = client.get("/api/market/akshare/catalog?q=spot")

    item = response.json()["capabilities"][0]
    assert item["param_docs"] == {}
    assert item["returns"] == ""


def test_catalog_filters_source_and_counts_every_source_unfiltered(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with patch(
            "src.market.infrastructure.akshare_tools.discover_stock_capabilities",
            return_value=_catalog_fixture(),
        ):
            response = client.get(
                "/api/market/akshare/catalog?source=%E6%96%B0%E6%B5%AA"
            )

    assert response.status_code == 200
    body = response.json()
    assert [item["name"] for item in body["capabilities"]] == ["stock_zh_a_spot_em"]
    assert body["total"] == 1
    # 聚合永远基于未过滤目录，否则左栏「工具 N」会随筛选忽大忽小。
    assert body["sources"] == [
        {"id": "东方财富", "label": "东方财富", "count": 2},
        {"id": "新浪", "label": "新浪", "count": 1},
    ]


def test_sources_endpoint_returns_counts_without_capability_payload(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with patch(
            "src.market.infrastructure.akshare_tools.discover_stock_capabilities",
            return_value=_catalog_fixture(),
        ):
            response = client.get("/api/market/akshare/sources")

    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == [
        {"id": "东方财富", "label": "东方财富", "count": 2},
        {"id": "新浪", "label": "新浪", "count": 1},
    ]
    assert body["total"] == 3
    # 货架只要数字；带上几千条能力明细就失去了这个端点的意义。
    assert "capabilities" not in body
    assert "enabled_total" not in body
    assert "enabled_max" not in body


def test_catalog_filters_category(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with patch(
            "src.market.infrastructure.akshare_tools.discover_stock_capabilities",
            return_value=_catalog_fixture(),
        ):
            response = client.get("/api/market/akshare/catalog?category=%E5%AE%9E%E6%97%B6%E8%A1%8C%E6%83%85")

    assert response.status_code == 200
    assert [item["name"] for item in response.json()["capabilities"]] == ["stock_zh_a_spot_em"]


def test_catalog_probe_delegates_only_to_controlled_catalog(tmp_path: Path) -> None:
    expected = {"elapsed_ms": 12.5, "rows": 2, "columns": ["date"], "sample": []}
    with _client(tmp_path) as client:
        with patch(
            "src.market.infrastructure.akshare_catalog.probe_stock_capability",
            return_value=expected,
        ) as probe:
            response = client.post(
                "/api/market/akshare/catalog/stock_zh_a_hist/probe",
                json={"params": {"symbol": "600519"}},
            )

    assert response.status_code == 200
    assert response.json() == expected
    probe.assert_called_once_with("stock_zh_a_hist", {"symbol": "600519"})


def test_catalog_probes_require_router_access() -> None:
    """试跑不写库也会访问第三方，独立挂载时同样必须鉴权。"""

    def deny(_: Request) -> None:
        raise HTTPException(status_code=401, detail="authentication required")

    app = FastAPI()
    app.include_router(build_akshare_catalog_router(write_dependency=deny))
    with TestClient(app) as client:
        single = client.post(
            "/api/market/akshare/catalog/stock_zh_a_hist/probe",
            json={"params": {}},
        )
        batch = client.post("/api/market/akshare/catalog/probe-batch", json={})

    assert single.status_code == 401
    assert batch.status_code == 401


def test_catalog_probe_returns_validation_error_for_unknown_or_unsafe_item(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with patch(
            "src.market.infrastructure.akshare_catalog.probe_stock_capability",
            side_effect=ValueError("目录中不存在该接口"),
        ):
            response = client.post(
            "/api/market/akshare/catalog/stock_zh_a_spot_em/probe",
            json={"params": {}},
        )

    assert response.status_code == 422
    assert "不存在" in response.json()["detail"]


def test_catalog_probe_rejects_invalid_path_or_payload_before_execution(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        malformed_name = client.post(
            "/api/market/akshare/catalog/stock_zh-a_hist/probe",
            json={"params": {}},
        )
        malformed_payload = client.post(
            "/api/market/akshare/catalog/stock_zh_a_hist/probe",
            json={"params": []},
        )

    assert malformed_name.status_code == 422
    assert malformed_payload.status_code == 422


def test_catalog_probe_rejects_oversized_body_before_execution(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with patch("src.market.infrastructure.akshare_catalog.probe_stock_capability") as probe:
            response = client.post(
                "/api/market/akshare/catalog/stock_zh_a_hist/probe",
                content=b"x" * (MAX_PROBE_REQUEST_BYTES + 1),
                headers={"content-type": "application/json"},
            )

    assert response.status_code == 413
    probe.assert_not_called()


def test_catalog_probe_maps_capacity_and_worker_start_failures(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with patch(
            "src.market.infrastructure.akshare_catalog.probe_stock_capability",
            side_effect=ProbeCapacityError("capacity"),
        ):
            capacity = client.post(
                "/api/market/akshare/catalog/stock_zh_a_hist/probe",
                json={"params": {}},
            )
        with patch(
            "src.market.infrastructure.akshare_catalog.probe_stock_capability",
            side_effect=ProbeWorkerStartError("spawn unavailable"),
        ):
            unavailable = client.post(
                "/api/market/akshare/catalog/stock_zh_a_hist/probe",
                json={"params": {}},
            )

    assert capacity.status_code == 429
    assert capacity.headers["retry-after"] == "2"
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"] == "spawn unavailable"
    # 这是「子进程起不动」不是「缺依赖」：不能带 capability 标记，否则前端会
    # 引导用户去装包。见 tests/app/test_capability_contract.py。
    assert "x-loci-reason" not in unavailable.headers


def test_catalog_lists_source_counts_without_enable_flags(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with patch(
            "src.market.infrastructure.akshare_tools.discover_stock_capabilities",
            return_value=_catalog_fixture(),
        ):
            body = client.get("/api/market/akshare/catalog").json()

    eastmoney = next(item for item in body["sources"] if item["id"] == "东方财富")
    assert eastmoney == {"id": "东方财富", "label": "东方财富", "count": 2}
    assert "enabled" not in eastmoney


def test_version_endpoint_reports_update_flag(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with patch(
            "src.market.api.akshare.check_akshare_version",
            return_value={
                "installed": "1.0.0",
                "latest": "1.2.0",
                "update_available": True,
                "pypi_url": "https://pypi.org/pypi/akshare/json",
                "error": None,
            },
        ):
            body = client.get("/api/market/akshare/version").json()
    assert body["installed"] == "1.0.0"
    assert body["latest"] == "1.2.0"
    assert body["update_available"] is True


def test_batch_probe_returns_paged_results(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with patch(
            "src.market.api.akshare.probe_stock_capabilities_batch",
            return_value={
                "results": [{"name": "stock_zh_a_hist", "ok": True, "error": None}],
                "ok": 1,
                "failed": 0,
                "skipped": 0,
                "missing": [],
                "offset": 0,
                "limit": 1,
                "next_offset": 1,
                "total_targets": 3,
                "done": False,
            },
        ):
            response = client.post(
                "/api/market/akshare/catalog/probe-batch",
                json={"offset": 0, "limit": 1},
            )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] == 1
    assert body["next_offset"] == 1
    assert body["done"] is False


def test_batch_probe_uses_short_default_page(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with patch(
            "src.market.api.akshare.probe_stock_capabilities_batch",
            return_value={
                "results": [],
                "ok": 0,
                "failed": 0,
                "skipped": 0,
                "missing": [],
                "offset": 0,
                "limit": DEFAULT_BATCH_PAGE,
                "next_offset": None,
                "total_targets": 0,
                "done": True,
            },
        ) as batch_probe:
            response = client.post("/api/market/akshare/catalog/probe-batch", json={})

    assert response.status_code == 200
    batch_probe.assert_called_once_with(names=None, offset=0, limit=DEFAULT_BATCH_PAGE)


def test_tool_enable_routes_are_gone(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        single = client.patch(
            "/api/market/akshare/tools/stock_zh_a_hist",
            json={"enabled": True},
        )
        batch = client.patch(
            "/api/market/akshare/tools",
            json={"names": ["stock_zh_a_hist"], "enabled": True},
        )
    assert single.status_code == 404
    assert batch.status_code == 404
