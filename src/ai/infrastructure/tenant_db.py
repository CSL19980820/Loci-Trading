"""AI 域的库路径解析：**一律惰性**，随当前租户走。

为什么单独一个模块
------------------
多租户之后 ``src.shared.paths.ops_db()`` / ``palace_db()`` 的返回值取决于
``current_tenant()``，也就是**取决于当前这个请求是谁发的**。任何在 import 期或
进程启动期把它算成字符串存下来的写法（模块级 ``DEFAULT_*_DB = xxx_db()``、
在 ``build_*_router`` 里 ``resolved = str(ops_db())``、构造期就绑好路径的单例）
都会让全进程所有用户共用第一个解析出来的那个库文件——隔离当场失效，而且不会
报错，只会静悄悄串味。

所以本域凡是「没有显式传路径」的地方，都必须在**调用时**经这里解析一次。
显式传进来的路径仍然优先：测试与单机固定库路径靠它。
"""
from __future__ import annotations

from pathlib import Path


def ops_db_for(override: str | Path | None = None) -> str:
    """当前租户的 ops.db（会话 / 供应商 / 用量都在这里）。"""
    if override:
        return str(override)
    from src.shared.paths import ops_db

    return str(ops_db())


def palace_db_for(override: str | Path | None = None) -> str:
    """当前租户的 palace.db（账本）。``PalaceStore`` 不接受 None，必须给准路径。"""
    if override:
        return str(override)
    from src.shared.paths import palace_db

    return str(palace_db())


def open_ops_store(override: str | Path | None = None):
    """按当前租户打开 ``OpsStore``。

    比 ``OpsStore(None)`` 稳：后者要靠 ops 侧自己惰性解析默认库，历史上那里是
    import 期求值的模块常量（见 ``src/ai/README.md`` 的审计表）。
    """
    from src.ops import OpsStore

    return OpsStore(ops_db_for(override))


__all__ = ["open_ops_store", "ops_db_for", "palace_db_for"]
