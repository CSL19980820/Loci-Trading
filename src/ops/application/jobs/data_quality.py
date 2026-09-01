r"""data_quality 任务：行情库日常体检。

为什么要有这个任务：把主源换成通达信、再做一次全量重写，只解决「当下」。
之后主源一旦被限流，回退源会安静地把合成成交额写回来；spot 会落下无回执的
临时行；退市票的水位会一直停在老日期。这些都不会报错，只会慢慢把库泡坏。

所以体检必须天天跑，且**只报不改**：修复各有各的入口，体检擅自动手会让
「谁改的库」说不清。超阈值时把中文告警塞进 payload，由通知链路推出去。
"""
from __future__ import annotations

import logging
from typing import Any

from src.ops.application.jobs.context import JobContext

logger = logging.getLogger(__name__)

#: 可从 Job 配置覆盖的阈值键。写死一份名单，避免把无关配置塞进阈值对象。
#: **新增阈值必须同步登记到这里**，否则运维页上调了也不生效——判据会安静地
#: 继续用默认值，看起来像「改了没用」，实际是这份名单没跟上。
_THRESHOLD_KEYS = (
    "min_authoritative_ratio",
    "max_fabricated_rows",
    "max_missing_receipts",
    "lookback_days",
    "min_last_day_coverage",
    "min_last_day_rows_floor",
    "min_last_day_authoritative_ratio",
    "max_last_day_provisional_ratio",
    "last_day_settle_hour",
    "min_index_close",
)


def _thresholds(config: dict[str, Any]):
    """Job 配置 → 阈值对象；非法值忽略并留默认，不因为配置写错就不体检。"""
    from src.market import QualityThresholds

    overrides: dict[str, Any] = {}
    for key in _THRESHOLD_KEYS:
        if key not in config:
            continue
        default = getattr(QualityThresholds(), key)
        try:
            overrides[key] = type(default)(config[key])
        except (TypeError, ValueError):
            logger.warning("体检阈值 %s=%r 非法，改用默认 %r", key, config[key], default)
    return QualityThresholds(**overrides)


def execute_data_quality(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """跑一遍行情库体检；有问题写中文告警，但**不改库、不抛异常**。

    不抛异常是刻意的：体检失败不该把运维页刷红——它报的是「库需要维护」，
    不是「这次任务出错了」。判据放在 payload 的 ``blocked`` / ``alert`` 里，
    由通知链路决定推不推。

    **告警必须留在返回值里**：``report`` 会原样落进 ``job_runs.result_json``，
    而 ``alert`` / ``blocked`` 正是 ``jobs/notify._maybe_push_wecom`` 的
    ``data_quality`` 分支唯一读的两个键。下面那条 ``logger.warning`` 只写本地
    日志文件，指望它「通知到人」等于没人知道；两条都留着，但别把日志当告警通道。
    """
    from src.market import inspect_market_data

    limits = _thresholds(config or {})
    with context.market() as store:
        report = inspect_market_data(store, thresholds=limits)
    if report.get("alert"):
        logger.warning("行情库体检告警：\n%s", report["alert"])
    report["config"] = {
        key: getattr(limits, key) for key in _THRESHOLD_KEYS
    }
    return report