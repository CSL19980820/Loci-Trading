"""进程级日志引导。独立成模块,因为它必须在**任何入口**都生效。

容器直接跑 ``python -m uvicorn src.app.main:app``(见 ``deploy/Dockerfile`` 的
CMD),**绕过了 ``cli/serve.py``**,也就绕过了 ``cli/*.py`` 里那几处
``logging.basicConfig``。没人配根 logger 时 Python 默认只放行 WARNING 及以上——
应用自己的 ``logger.info`` 因此在生产上**一条都看不到**。

2026-08-26 实测:线上整段启动日志只有 11 行,「调度器已启动,装载 N 个任务」、
「二波监测已退役」、「托管任务已确保」全部静默丢弃。代价是排障基本靠猜——
查一个僵尸定时任务时,无法从日志判断启动期的 ensure 跑没跑、跑到哪步失败,
只能靠比对 ``jobs.updated_at`` 反推。而唯一能透出来的是 ``logger.warning``
(Python 的 lastResort 处理器),于是日志里只剩故障、没有上下文:
**最需要日志的时候恰恰什么都没有。**
"""
from __future__ import annotations

import logging
import os

#: 默认级别。生产要的是「能复盘启动与调度发生了什么」,INFO 是最低够用档。
DEFAULT_LOG_LEVEL = "INFO"
#: 覆盖用环境变量(``DEBUG`` / ``WARNING`` …)。
LOG_LEVEL_ENV = "LOCI_LOG_LEVEL"


def configure_logging() -> bool:
    """给根 logger 装一个处理器;已有配置时**不覆盖**。返回是否真的配了。

    幂等且不夺权是硬要求:``create_app`` 在测试里会被反复调用,CLI 入口也各有
    自己的 ``basicConfig``。``logging.basicConfig`` 在根 logger 已有 handler 时
    本就是 no-op,这里再显式判一次——把意图写在代码里,而不是依赖那个隐式行为。

    只动根 logger,不碰 uvicorn 自己的 ``uvicorn`` / ``uvicorn.access`` logger:
    它们由 uvicorn 的 log config 管,插手会把访问日志格式弄乱。
    """
    if logging.getLogger().handlers:
        return False
    raw = (os.environ.get(LOG_LEVEL_ENV) or DEFAULT_LOG_LEVEL).strip().upper()
    # 无效级别名不能让进程起不来——日志配置炸掉服务本末倒置,回落 INFO。
    level = getattr(logging, raw, None)
    if not isinstance(level, int):
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return True
