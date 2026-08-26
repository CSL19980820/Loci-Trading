"""503 的两种成因必须能被前端区分。

后端用同一个 503 表示「缺依赖」和「SQLite 短暂繁忙 / 子进程起不动」。前端
（``shared/api/quant_client.ts``）只对前者抛 ``CapabilityUnavailableError`` 并
引导用户装依赖；一旦把繁忙也判成缺依赖，用户会在锁竞争时被指去装包，装了也没用。
区分靠的就是这里断言的响应头。
"""
from __future__ import annotations

from src.shared.api_deps import CAPABILITY_MISSING_HEADER, CAPABILITY_MISSING_VALUE, missing_dependency


def test_missing_dependency_carries_the_capability_marker() -> None:
    exc = missing_dependency(ImportError("No module named 'pandas'", name="pandas"))

    assert exc.status_code == 503
    assert exc.headers is not None
    assert exc.headers[CAPABILITY_MISSING_HEADER] == CAPABILITY_MISSING_VALUE
    assert "pandas" in exc.detail


def test_missing_dependency_detail_points_at_a_file_that_exists() -> None:
    """曾经指向 deploy/requirements-runtime.txt——那个文件和目录都不存在。"""
    detail = missing_dependency(ImportError("boom", name="akshare")).detail

    assert "deploy/" not in detail
    assert "requirements.txt" in detail
