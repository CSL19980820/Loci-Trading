"""P0-3：并行题材拉取不透传主线程 MarketStore（方案 B）。"""
from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from src.market import MarketStore, make_legacy_tape_call
from src.market.domain.tape import TapeRequest, TapeResult
from src.market.infrastructure.adapters.types import TAPE_LANES
from src.ops.application.skill_watch.leader_map import scan_leader_map


class _ThemeProvider:
    provider_id = "local_fake"
    lanes = TAPE_LANES

    def __init__(self) -> None:
        self.contexts: list[dict[str, Any]] = []

    def fetch(self, request: TapeRequest) -> TapeResult:
        ctx = dict(request.context or {})
        self.contexts.append(ctx)
        theme = str(
            (request.arguments or {}).get("themeName")
            or (request.arguments or {}).get("themeCode")
            or "T"
        )
        return TapeResult(
            data={
                "actualTradeDate": request.requested_date or "2026-08-07",
                "dateStatus": "exact",
                "themeName": theme,
                "rows": [
                    {
                        "code": "600001",
                        "name": "测票",
                        "themeName": theme,
                        "pct_chg": 5.0,
                    }
                ],
            }
        )


def test_worker_call_strips_injected_market_store() -> None:
    """allow_injected_store=False 时 context 不含主线程 store。"""
    marker = object()
    provider = _ThemeProvider()
    call = make_legacy_tape_call(store=marker, providers=[provider])

    call("theme_stocks", {"themeName": "本地科技", "limit": 2})
    call(
        "theme_stocks",
        {"themeName": "本地科技", "limit": 2},
        allow_injected_store=False,
    )

    assert provider.contexts[0].get("market_store") is marker
    assert "market_store" not in provider.contexts[1]


def test_leader_map_parallel_theme_fetch_skips_serial_fallback(monkeypatch: Any) -> None:
    """并行段 rows 非空 → 不触发整批串行兜底；且请求 allow_injected_store=False。"""
    theme_calls: list[dict[str, Any]] = []
    # 本测试只验证题材并发；日 K 路由必须隔离，否则缺失夹具会穿透真实外部行情源。
    monkeypatch.setattr(
        "src.ops.application.skill_watch.leader_map._daily_frames",
        lambda *args, **kwargs: {},
    )

    def call_tool(name: str, args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        if name == "short_term_emotion":
            return {
                "structured": {
                    "limitUpCount": 40,
                    "brokenLimitUpCount": 5,
                    "limitDownCount": 2,
                }
            }
        if name == "limit_up_ladder":
            return {"structured": {"highestBoard": 3, "boardSummary": [{"level": 1, "count": 10}]}}
        if name == "theme_intraday_capital":
            return {
                "structured": {
                    "rows": [
                        {"themeCode": "A", "themeName": "题材A", "strength": 90},
                        {"themeCode": "B", "themeName": "题材B", "strength": 80},
                        {"themeCode": "C", "themeName": "题材C", "strength": 70},
                    ]
                }
            }
        if name == "theme_stocks":
            theme_calls.append({"args": dict(args), "kwargs": dict(kwargs)})
            code = str(args.get("themeCode") or "X")
            return {
                "structured": {
                    "rows": [
                        {
                            "code": f"60000{len(theme_calls)}",
                            "name": f"票{code}",
                            "themeCode": code,
                            "pct_chg": 3.0,
                            "amount": 1e8,
                        }
                    ]
                }
            }
        return {"structured": {}}

    result = scan_leader_map(
        call_tool,
        trade_date="2026-08-07",
        tuning={
            "stages": {
                "market_gate": False,
                "theme_interval": False,
                "role_history": False,
            },
            "scan": {"theme_limit": 3, "member_limit": 5},
        },
        market_store=object(),
    )

    assert len(theme_calls) == 3, "并行成功不应整批串行重跑（应为 3 次非 6 次）"
    assert all(c["kwargs"].get("allow_injected_store") is False for c in theme_calls)
    assert result.get("themes") or result.get("entries") is not None


def test_cross_thread_sqlite_store_reuse_raises(tmp_path: Path) -> None:
    """反向：工作线程复用主线程 MarketStore.conn → ProgrammingError。"""
    store = MarketStore(tmp_path / "market.db")
    errors: list[BaseException] = []

    def _touch() -> None:
        try:
            store.conn.execute("SELECT 1").fetchone()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    try:
        store.conn.execute("SELECT 1").fetchone()  # 主线程 OK
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(_touch).result(timeout=5)
    finally:
        store.close()

    assert errors, "跨线程复用应失败"
    assert isinstance(errors[0], sqlite3.ProgrammingError)
