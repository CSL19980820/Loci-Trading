"""AI 战法工具必须与网页和 Job 共用同一条选股容量闸门。"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading

from src.ai.application.system_toolbus import build_system_toolbus
from src.shared.screen_capacity import screen_capacity_permit


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


def test_strategy_screen_tool_fails_fast_when_capacity_is_taken(tmp_path: Path) -> None:
    bus = build_system_toolbus(
        palace_db=str(tmp_path / "palace.db"),
        market_db=str(tmp_path / "market.db"),
        ops_db=str(tmp_path / "ops.db"),
    )

    with _held_capacity():
        result = bus.executor(
            "strategy_screen", {"strategy": "qianlong-close-v3"}
        )

    assert result["is_error"] is True
    assert "容量" in result["text"]
