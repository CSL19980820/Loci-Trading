"""HTTP 路由模块。

账本相关的路由仍留在 src/palace_api.py（它们与鉴权、SPA 托管耦合较紧）；
行情、策略、回测、技能、任务、供应商这些新增能力放在这里，
因为它们依赖可选的重量级第三方库，需要独立的降级路径。
"""
from src.routers.quant import build_quant_router

__all__ = ["build_quant_router"]
