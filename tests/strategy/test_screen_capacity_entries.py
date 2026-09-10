"""同步 HTTP 选股入口必须服从共享的进程级容量许可。"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading

import pytest
from fastapi import HTTPException

from src.shared.screen_capacity import screen_capacity_permit
from src.strategy.api.router import build_strategy_router
from src.strategy.api.schemas import ScreenRequest


@contextmanager
def _held_capacity():
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def hold() -> None:
        try:
            with screen_capacity_permit(label="test-holder", wait_sec=None):
                entered.set()
                release.wait(timeout=10)
        except BaseException as exc:  # noqa: BLE001 - 交回主线程断言
            errors.append(exc)
            entered.set()

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert entered.wait(3), "测试占位没有拿到选股容量"
    assert not errors
    try:
        yield
    finally:
        release.set()
        thread.join(timeout=5)
        assert not thread.is_alive()


def _endpoint(router, path: str):
    return next(
        route.endpoint
        for route in router.routes
        if getattr(route, "path", "") == path
    )


def test_sync_screen_returns_retryable_429_when_capacity_is_taken(tmp_path: Path) -> None:
    router = build_strategy_router(
        write_dependency=lambda: None,
        market_db=str(tmp_path / "market.db"),
        ops_db=str(tmp_path / "ops.db"),
        palace_db=str(tmp_path / "palace.db"),
    )
    endpoint = _endpoint(router, "/api/strategies/screen")

    with _held_capacity(), pytest.raises(HTTPException) as caught:
        endpoint(ScreenRequest(strategy="qianlong-close-v3"), _write=None)

    assert caught.value.status_code == 429
    assert "容量" in str(caught.value.detail)


def test_screen_today_returns_retryable_429_when_capacity_is_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.strategy.api import screen_today_router

    monkeypatch.setattr(screen_today_router, "should_sync_today", lambda _db: False)
    router = screen_today_router.build_screen_today_router(
        write_dependency=lambda: None,
        market_db=str(tmp_path / "market.db"),
        palace_db=str(tmp_path / "palace.db"),
    )
    endpoint = _endpoint(router, "/api/screen/today")

    with _held_capacity(), pytest.raises(HTTPException) as caught:
        endpoint(
            strategy="qianlong-close-v3",
            force_sync=False,
            date=None,
            record_candidates=False,
            top_n=0,
            _write=None,
        )

    assert caught.value.status_code == 429
    assert "容量" in str(caught.value.detail)
