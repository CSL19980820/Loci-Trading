"""intraday_capture 任务执行器：盘中留存带的每日采集。

**为什么必须托管而不是让人手动跑**：这批数据上游没有历史（AkShare 侧 21 个接口只有
当天快照，东财 `trends2` 的 `ndays` 上限是 5），漏一天就永久缺一天。靠人记得每天点
一次，等于一定会漏。见 `docs/adr/ADR-014-encrypted-intraday-tape-retention.md`。

**为什么部分失败不算任务失败**：一轮六个上游，AkShare 打的是公开网页接口，
`RemoteDisconnected` 是常态。一个源挂掉就把整轮判失败，会让运维页天天飘红，最后没人
看它——那比失败本身更糟。所以：**一个都没采到才算失败**，部分成功记 `partial` 并把
失败清单原样写进 payload。
"""
from __future__ import annotations

from typing import Any

from src.ops.application.jobs.context import JobContext, JobError


def execute_intraday_capture(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """采集今日盘中快照并加密落盘。

    config：
    - ``datasets``：只采这几个（列表）。缺省采 `default_specs()` 全部。
    - ``trade_date``：覆盖交易日，仅补采历史目录时用。
    """
    from src.market import capture_snapshots, default_specs
    from src.shared.paths import data_dir

    specs = default_specs()
    wanted = config.get("datasets")
    if isinstance(wanted, (list, tuple)) and wanted:
        names = {str(item).strip() for item in wanted if str(item).strip()}
        specs = [item for item in specs if item.dataset in names]
        if not specs:
            raise JobError(f"没有匹配的数据集：{sorted(names)}")

    trade_date = str(config.get("trade_date") or "").strip() or None
    report = capture_snapshots(data_dir(), specs, trade_date=trade_date)
    body = report.to_dict()

    if not report.captured:
        raise JobError(
            f"盘中留存全部失败（{body['failure_count']} 项）："
            + "；".join(f"{item['dataset']}:{item['error'][:60]}" for item in body["failures"])
        )

    body["status"] = "ok" if report.ok else "partial"
    body["summary"] = (
        f"{body['trade_date']} 采集 {body['captured_count']} 项"
        f"（失败 {body['failure_count']}）｜加密 {body['protection']}"
    )
    return body


__all__ = ["execute_intraday_capture"]
