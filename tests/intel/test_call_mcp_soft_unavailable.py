from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from src.intel.application.fetch import call_mcp_tool
from src.intel.infrastructure.intel_cache import (
    read_cached_snapshot,
    write_cached_snapshot,
)
from src.market import MarketStore


def test_call_mcp_tool_soft_fails_when_wudao_unavailable_without_quota() -> None:
    with (
        patch(
            "src.intel.application.fetch.wudao_availability",
            return_value={"available": False, "reason": "悟道 MCP 未配置 API Key"},
        ),
        patch("src.intel.application.fetch.acquire_quota") as acquire,
        patch("src.intel.application.fetch.quota_snapshot", return_value={"ok": True}),
        patch("src.intel.infrastructure.registry.build_client") as build,
    ):
        payload = call_mcp_tool("short_term_emotion", {}, server="wudao")
    assert payload["is_error"] is True
    assert payload["unavailable"] is True
    assert "未配置" in payload["unavailable_reason"]
    acquire.assert_not_called()
    build.assert_not_called()


def test_call_mcp_tool_still_serves_cache_when_wudao_down() -> None:
    cached = {
        "tool": "short_term_emotion",
        "structured": {"limitUpCount": 12},
        "is_error": False,
        "text": "{}",
    }
    store = object()
    with (
        patch(
            "src.intel.application.fetch.read_cached_snapshot",
            return_value=cached,
        ),
        patch(
            "src.intel.application.fetch.wudao_availability",
            return_value={"available": False, "reason": "down"},
        ) as availability,
        patch("src.intel.application.fetch.quota_snapshot", return_value={}),
        patch("src.intel.application.fetch.acquire_quota") as acquire,
    ):
        payload = call_mcp_tool(
            "short_term_emotion",
            {},
            server="wudao",
            cache=True,
            market_store=store,  # type: ignore[arg-type]
        )
    assert payload["cached"] is True
    assert payload["structured"]["limitUpCount"] == 12
    availability.assert_not_called()
    acquire.assert_not_called()


def test_cached_snapshot_declares_when_it_was_fetched(tmp_path: Path) -> None:
    """缓存命中必须带「哪一刻抓的」；否则盘中会把早盘快照当实时用。"""
    store = MarketStore(tmp_path / "market.db")
    try:
        write_cached_snapshot(
            store,
            trade_date="2026-08-07",
            tool="short_term_emotion",
            arguments={},
            server="wudao",
            payload={"structured": {"limitUpCount": 12}, "is_error": False},
        )
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=97)).isoformat(
            timespec="seconds"
        )
        store.conn.execute("UPDATE intel_snapshots SET fetched_at = ?", (stamp,))
        store.conn.commit()

        cached = read_cached_snapshot(
            store,
            trade_date="2026-08-07",
            tool="short_term_emotion",
            arguments={},
        )
    finally:
        store.close()

    assert cached is not None
    assert cached["cache_fetched_at"] == stamp
    assert 96 <= cached["cache_age_minutes"] <= 99


def test_naive_cache_timestamp_does_not_explode(tmp_path: Path) -> None:
    """旧库里可能有不带时区的 fetched_at：按缓存不可信处理，不能抛到调用方。"""
    store = MarketStore(tmp_path / "market.db")
    try:
        write_cached_snapshot(
            store,
            trade_date="2026-08-07",
            tool="short_term_emotion",
            arguments={},
            server="wudao",
            payload={"structured": {"limitUpCount": 12}, "is_error": False},
        )
        store.conn.execute("UPDATE intel_snapshots SET fetched_at = '2026-08-07T09:31:00'")
        store.conn.commit()

        assert (
            read_cached_snapshot(
                store,
                trade_date="2026-08-07",
                tool="short_term_emotion",
                arguments={},
                max_age_minutes=5,
            )
            is None
        )
    finally:
        store.close()
