"""龙头角色常量：单一真相源，避免 leader_map / role_stats / 推送文案漂移。"""
from __future__ import annotations

#: 角色按「结构是否还在」排序，越靠前越强。
LEADER_ROLES = ("leader", "secondary", "follower", "weakened", "failed")

#: 结构已破坏或正在走弱，持仓命中即为退出证据。
EXIT_ROLES = ("weakened", "failed")

ROLE_LABEL = {
    "leader": "龙头",
    "secondary": "中军",
    "follower": "跟风",
    "weakened": "走弱",
    "failed": "结构破坏",
}

__all__ = ["EXIT_ROLES", "LEADER_ROLES", "ROLE_LABEL"]
