"""调度/推送热路径不得往工作目录写调试日志。

曾经有三处遗留的 ``debug-19ad13.log`` 追加写：``validate_cron`` 每次校验、
预览每次出结果、每条跟随推送理由清洗都会落一行 JSON 到进程 CWD，
既污染安装目录又在热路径上白白做磁盘 IO。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.ops.application.jobs.paper_follow_push import scrub_follow_reason
from src.ops.application.trading_schedule import preview_trading_runs
from src.ops.infrastructure.scheduler import validate_cron


@pytest.fixture()
def _cwd(tmp_path: Path):
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(previous)


def test_hot_paths_write_no_debug_log(_cwd: Path) -> None:
    validate_cron("30 15 * * mon-fri")
    preview_trading_runs(
        "interval",
        interval_minutes=10,
        window_start_hour=9,
        window_start_minute=30,
        window_end_hour=14,
        window_end_minute=50,
        limit=3,
    )
    scrub_follow_reason("gap_up 情景预案不买（情景预案不买）")

    assert list(_cwd.glob("*.log")) == []
