r"""托管：行情库数据体检（幂等确保）。

换源与全量重写都是一次性动作，只解决当下。之后主源被限流、回退源把合成成交额
写回来、spot 落下无回执行——这些都不报错，只会慢慢把库泡坏。所以体检要天天跑。
"""
from __future__ import annotations

from typing import Any

from src.ops.infrastructure.store_helpers import MANAGED_MARKET_QUALITY

#: 默认点：热库重建（16:10）之后，当日全链路已经落定，体检看到的是终态。
MARKET_QUALITY_CRON = "30 16 * * mon-fri"

#: 阈值默认留空 = 用 ``QualityThresholds`` 的默认值，不在这里抄第二份。
#:
#: ``push_wecom`` 是唯一的例外，而且**必须默认开**：体检天天跑、只读只报，
#: 报出来的东西如果只落在 ``job_runs.result_json`` 和本地日志里，就要靠人主动
#: 去运维页翻——而「主源今天开始退化」恰恰是那种不翻就不会知道、每多一天就多
#: 一天脏数据的问题。默认关等于把这条防线的最后一段留空。
#:
#: 不推的那一半交给 ``jobs/notify._maybe_push_wecom`` 的 ``data_quality``
#: 分支：全绿一律 ``push_skipped``，只有 ``blocked`` 或有 ``alert`` 才出声。
#: 所以「默认开」不会变成天天一条正常播报。
DEFAULT_MARKET_QUALITY_CONFIG: dict[str, Any] = {"push_wecom": True}


def ensure_managed_market_quality_job(store: Any) -> dict[str, Any]:
    r"""确保「行情库体检」托管任务存在（工作日 16:30）。

    已有任务只**补齐缺失的配置键**，不强改 enabled / cron，也不覆盖用户已经
    改过的值——``{**DEFAULT, **prev}`` 的顺序就是这个语义：默认值垫底，库里
    存着的赢。运维在页面上关掉推送或改了时间，下次启动不能被 ensure 顶回去，
    与其它 ``ensure_managed_*`` 一致。
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