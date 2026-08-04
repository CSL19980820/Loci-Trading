"""实时行情用例：为 API 提供稳定的行情快照入口。"""
from __future__ import annotations

from typing import Any


def build_live_tape(
    *,
    position_codes: list[dict[str, Any]] | None = None,
    extra_codes: list[str] | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """组装任务栏行情快照，隐藏实时适配器的实现细节。"""
    from src.market.infrastructure.live_tape import build_live_tape as _build_live_tape

    return _build_live_tape(
        position_codes=position_codes,
        extra_codes=extra_codes,
        use_cache=use_cache,
    )


def fetch_live_quotes(
    codes: list[str],
    *,
    instrument_types: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """读取行情台当前页实时行情。"""
    from src.market.infrastructure.live_tape import fetch_live_quotes as _fetch_live_quotes

    return _fetch_live_quotes(codes, instrument_types=instrument_types)
