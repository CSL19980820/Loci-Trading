"""监测默认阈值叶模块：打断 tuning ↔ leader_map / market_regime 加载环。"""
from __future__ import annotations

DEFAULT_GATE_PARAMS: dict[str, float] = {
    "promotion_attack": 0.35,
    "promotion_empty": 0.20,
    "broken_empty": 0.45,
    "broken_attack_max": 0.30,
    "min_height_attack": 3.0,
    "theme_strength_attack": 60.0,
    "theme_strength_empty": 35.0,
    "breadth_attack": 0.55,
    "breadth_empty": 0.35,
    "temperature_attack": 60.0,
    "temperature_empty": 30.0,
}

DEFAULT_ROLE_PARAMS: dict[str, float] = {
    "leader_min_level": 2.0,
    "leader_min_gain_20": 15.0,
    "secondary_min_level": 2.0,
    "weakened_drawdown": 25.0,
    "failed_ma20_ratio": 0.94,
    "failed_vol_ratio": 1.2,
}

__all__ = ["DEFAULT_GATE_PARAMS", "DEFAULT_ROLE_PARAMS"]
