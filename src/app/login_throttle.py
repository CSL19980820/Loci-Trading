"""登录失败限流（组合根用）。"""
from __future__ import annotations

import time


class LoginThrottle:
    """登录失败限流，防止固定口令被暴力枚举。

    单容器单进程部署，用内存计数就够；进程重启计数清零，这是已知取舍。
    它只是下限保护，真正的边界仍是 PALACE_AUTH_PASSWORD 的熵值，
    以及 HTTPS 部署下 Nginx 那层 Basic Auth。
    """

    def __init__(self, *, max_failures: int = 5, window_seconds: int = 900) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str, now: float) -> list[float]:
        cutoff = now - self.window_seconds
        recent = [stamp for stamp in self._failures.get(key, []) if stamp > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def retry_after(self, key: str) -> int:
        """仍在锁定期内返回剩余秒数；未锁定返回 0。"""
        now = time.monotonic()
        recent = self._recent(key, now)
        if len(recent) < self.max_failures:
            return 0
        return max(1, int(self.window_seconds - (now - recent[0])))

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        recent = self._recent(key, now)
        recent.append(now)
        self._failures[key] = recent
        self._prune(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)

    def _prune(self, now: float) -> None:
        """伪造来源 IP 可以刷出大量条目，超阈值时清掉已过期的键。"""
        if len(self._failures) <= 1024:
            return
        cutoff = now - self.window_seconds
        for key in [
            key
            for key, stamps in self._failures.items()
            if not any(stamp > cutoff for stamp in stamps)
        ]:
            self._failures.pop(key, None)
