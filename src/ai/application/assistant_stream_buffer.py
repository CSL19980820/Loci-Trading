"""流式 token/think 内存批写：合并 delta，降低每增量一次事务 INSERT。"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

_BUFFERED_TYPES = frozenset({"token", "think"})
_CHAR_THRESHOLD = 120
_FLUSH_INTERVAL_MS = 120.0

PersistFn = Callable[[str, dict[str, Any]], None]


class StreamEventBuffer:
    """仅缓冲 ``token``/``think``；其它类型先 flush 再立即落库。"""

    def __init__(self, persist: PersistFn) -> None:
        self._persist = persist
        self._event_type: str | None = None
        self._delta = ""
        self._last_flush_mono = time.monotonic()

    def emit(self, payload: dict[str, Any]) -> None:
        etype = str(payload.get("type") or "event")
        if etype not in _BUFFERED_TYPES:
            self.flush()
            self._persist(etype, payload)
            return
        delta = str(payload.get("delta") or "")
        if not delta:
            return
        if self._event_type is not None and self._event_type != etype:
            self.flush()
        self._event_type = etype
        self._delta += delta
        if len(self._delta) >= _CHAR_THRESHOLD or self._elapsed_ms() >= _FLUSH_INTERVAL_MS:
            self.flush()

    def flush(self) -> None:
        etype = self._event_type
        delta = self._delta
        self._event_type = None
        self._delta = ""
        self._last_flush_mono = time.monotonic()
        if not etype or not delta:
            return
        self._persist(etype, {"type": etype, "delta": delta})

    def _elapsed_ms(self) -> float:
        return (time.monotonic() - self._last_flush_mono) * 1000.0
