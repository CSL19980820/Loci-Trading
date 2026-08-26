"""盘口情报 tape provider 骨架。"""

from src.market.infrastructure.tape.base import TapeProvider, TapeProviderError
from src.market.infrastructure.tape.cache_provider import CachedTapeProvider
from src.market.infrastructure.tape.legacy_bridge import (
    LEGACY_TOOL_TO_LANE,
    legacy_call_tool,
    make_legacy_tape_call,
)
from src.market.infrastructure.tape.local_provider import LocalTapeProvider
from src.market.infrastructure.tape.registry import (
    all_providers,
    providers_for_lane,
    register_provider,
    reset_registry,
)
from src.market.infrastructure.tape.router import (
    clear_provider_cooldown,
    fetch_tape,
    route_tape,
    tape_readiness,
)

__all__ = [
    "TapeProvider",
    "TapeProviderError",
    "CachedTapeProvider",
    "LEGACY_TOOL_TO_LANE",
    "LocalTapeProvider",
    "all_providers",
    "clear_provider_cooldown",
    "fetch_tape",
    "legacy_call_tool",
    "make_legacy_tape_call",
    "providers_for_lane",
    "register_provider",
    "reset_registry",
    "route_tape",
    "tape_readiness",
]
