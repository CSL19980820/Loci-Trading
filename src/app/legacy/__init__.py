"""过渡期聚合路由（原 quant.py）；按上下文拆分前由此挂载。"""
from src.app.legacy.quant_router import build_quant_router

__all__ = ["build_quant_router"]
