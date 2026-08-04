"""组合根的惰性导出。

业务 API 可能需要导入 ``src.app.legacy`` 中的兼容模型；导入包时立即
构建整棵 FastAPI 应用会反向加载这些 API，形成循环依赖。
"""
from typing import Any

__all__ = ["app", "create_app"]


def __getattr__(name: str) -> Any:
    if name == "app":
        from src.app.main import app

        globals()[name] = app
        return app
    if name == "create_app":
        from src.app.main import create_app

        globals()[name] = create_app
        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
