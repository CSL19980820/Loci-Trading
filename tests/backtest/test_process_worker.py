from __future__ import annotations

from pathlib import Path

import pytest

from src.backtest import (
    ProcessWorkerCancelled,
    ProcessWorkerError,
    ProcessWorkerTimedOut,
    run_isolated_job,
)


def test_isolated_compare_uses_spawn_and_returns_execution_receipt(tmp_path: Path) -> None:
    """真实 spawn 路径至少要能在空行情库上受控收口。"""
    result = run_isolated_job(
        "compare",
        {"strategies": [], "holds": [1], "benchmark": None},
        market_db=str(tmp_path / "market.db"),
        tenant_id="__primary__",
        timeout_seconds=20,
    )

    assert result["execution"]["mode"] == "process"
    assert result["execution"]["operation"] == "compare"
    assert result["execution"]["worker_pid"] > 0
    assert result["rows"] == []


def test_isolated_worker_honours_parent_cancellation(tmp_path: Path) -> None:
    with pytest.raises(ProcessWorkerCancelled, match="按请求取消"):
        run_isolated_job(
            "compare",
            {"strategies": [], "holds": [1], "benchmark": None},
            market_db=str(tmp_path / "market.db"),
            tenant_id="__primary__",
            timeout_seconds=20,
            cancel_check=lambda: True,
        )


def test_isolated_worker_rejects_unknown_operation(tmp_path: Path) -> None:
    with pytest.raises(ProcessWorkerError, match="不支持"):
        run_isolated_job(
            "screen",
            {},
            market_db=str(tmp_path / "market.db"),
            tenant_id="__primary__",
        )


def test_isolated_worker_rejects_an_expired_parent_budget(tmp_path: Path) -> None:
    with pytest.raises(ProcessWorkerTimedOut, match="没有剩余"):
        run_isolated_job(
            "compare",
            {"strategies": [], "holds": [1], "benchmark": None},
            market_db=str(tmp_path / "market.db"),
            tenant_id="__primary__",
            timeout_seconds=0,
        )
