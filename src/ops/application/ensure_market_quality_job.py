r"""托管：行情库数据体检（幂等确保）。

换源与全量重写都是一次性动作，只解决当下。之后主源被限流、回退源把合成成交额
写回来、spot 落下无回执行——这些都不报错，只会慢慢把库泡坏。所以体检要天天跑。
"""
from __future__ import annotations

from typing import Any

from src.ops.infrastructure.store_helpers import MANAGED_MARKET_QUALITY

#: 默认点：热库重建（16:10）之后，当日全链路已经落定，体检看到的是终态。
MARKET_QUALITY_CRON = "30 16 * * mon-fri"

#: 阈值默认留空 = 用 ``QualityThresholds`` 的默认值。写在这里只是让运维页
#: 能看到有哪些旋钮可调，不是把默认值抄第二份。
DEFAULT_MARKET_QUALITY_CONFIG: dict[str, Any] = {}


def ensure_managed_market_quality_job(store: Any) -> dict[str, Any]:
    """确保「行情库体检」托管任务存在（工作日 16:30）。

    已有任务只补配置，不强改 enabled / cron——尊重运维页开关，
    与其它 ensure_managed_* 语义一致。
    """
    existing = store.get_job_by_name(MANAGED_MARKET_QUALITY)
    if existing is None:
        store.create_job(
            name=MANAGED_MARKET_QUALITY,
            kind="data_quality",
            cron=MARKET_QUALITY_CRON,
            config=dict(DEFAULT_MARKET_QUALITY_CONFIG),
            enabled=True,
        )
        return {"created": 1, "updated": 0}
    prev = existing.get("config") if isinstance(existing.get("config"), dict) else {}
    merged = {**DEFAULT_MARKET_QUALITY_CONFIG, **prev}
    store.update_job(existing["id"], config=merged)
    return {"created": 0, "updated": 1}