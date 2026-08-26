"""情报缓存故障不得改变取数结论。

缓存是可重建的派生数据。行情同步正锁着 market.db 时，读写缓存都可能抛错；
若那时把已经真调过、已经扣过配额的成功结果丢掉，采集作业会成片假失败。
"""
from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import patch

import pytest

from src.intel.application.fetch import call_mcp_tool


class _StubClient:
    """顶替 McpClient；isinstance 检查一并 patch 成本类。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, arguments))
        return {"text": '{"limitUpCount": 12}', "is_error": False}


def _patched_call(**overrides: Any):
    client = _StubClient()
    patches = {
        "src.intel.application.fetch.McpClient": _StubClient,
        "src.intel.infrastructure.registry.build_client": lambda _server: client,
        "src.intel.application.fetch.is_resident_wudao_server": lambda _server: False,
        "src.intel.application.fetch.acquire_quota": lambda _pool: None,
        "src.intel.application.fetch.record_quota_call": lambda _pool: None,
        "src.intel.application.fetch.quota_snapshot": lambda: {},
        "src.intel.application.fetch.trade_date_today": lambda: "2026-08-07",
        **overrides,
    }
    return client, patches


def _run(patches: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    stack = [patch(target, value) for target, value in patches.items()]
    for item in stack:
        item.start()
    try:
        return call_mcp_tool("short_term_emotion", {}, server="other", **kwargs)
    finally:
        for item in reversed(stack):
            item.stop()


def _boom(*_args: Any, **_kwargs: Any) -> Any:
    raise sqlite3.OperationalError("database is locked")


def test_cache_write_failure_keeps_the_paid_for_result() -> None:
    client, patches = _patched_call(
        **{"src.intel.application.fetch.write_cached_snapshot": _boom}
    )
    store = object()

    payload = _run(patches, cache=True, market_store=store)

    assert payload["is_error"] is False
    assert payload["structured"]["limitUpCount"] == 12
    assert client.calls, "真调用发生过，结果不能因为落缓存失败被丢弃"


def test_cache_read_failure_falls_back_to_a_real_call() -> None:
    client, patches = _patched_call(
        **{
            "src.intel.application.fetch.read_cached_snapshot": _boom,
            "src.intel.application.fetch.write_cached_snapshot": lambda *a, **k: None,
        }
    )
    store = object()

    payload = _run(patches, cache=True, market_store=store)

    assert payload["structured"]["limitUpCount"] == 12
    assert len(client.calls) == 1


def test_cache_without_a_store_is_a_miss_not_a_silent_no_op() -> None:
    """不传 store 时 cache=True 是空转：这里钉住现状，避免误以为已经省了配额。"""
    client, patches = _patched_call()

    payload = _run(patches, cache=True)

    assert payload["cached"] is False
    assert len(client.calls) == 1


@pytest.mark.parametrize("flag", [True, False])
def test_truncated_flag_is_carried_into_the_payload(flag: bool) -> None:
    """正文截断标记必须透传：下游据此判断「解析失败」而不是「今天没数据」。"""

    class _Truncating(_StubClient):
        def call_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            self.calls.append((tool, arguments))
            return {
                "text": '{"limitUpCount": 12}',
                "is_error": False,
                "truncated": flag,
            }

    client = _Truncating()
    _, patches = _patched_call()
    patches["src.intel.infrastructure.registry.build_client"] = lambda _server: client
    patches["src.intel.application.fetch.McpClient"] = _Truncating

    payload = _run(patches)

    assert payload["truncated"] is flag
