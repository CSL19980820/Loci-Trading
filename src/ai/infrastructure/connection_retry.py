"""只重试上游尚未执行的请求，保留 Client 的代理、证书和流式行为。

两类可安全重放的失败：
- 发送前的连接失败（ConnectError/ConnectTimeout）：业务请求还没发出去；
- 上游明确拒收的忙碌响应（429 限流 / 503 不可用 / 529 过载）：请求被拒、没有开始生成。
  一次瞬时限流原先就能让整轮助手或咨询直接失败。只重试有限次数，``Retry-After``
  超过上限时不等，原样把错误交给调用方；gRPC 网关可能已经执行请求，不重放。
读写失败、已开始的流、余额或参数错误（其余 4xx/5xx）都不在重试范围内。
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx2

from src.shared.http_protocol import record_http_protocol

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 503, 529})
MAX_STATUS_RETRIES = 2
MAX_RETRY_AFTER_SECONDS = 8.0


def status_retry_delay(response: Any, retries: int, *, budget: float | None = None) -> float | None:
    """上游拒收后下一次重试前的等待秒数；``None`` 表示不重试、原样返回响应。

    ``budget`` 是调用方还能花在等待上的秒数（剩余期限或单次超时）；等待本身
    超出预算时不重试，免得把期限耗在睡眠上。
    """
    if response.status_code not in RETRYABLE_STATUS or retries >= MAX_STATUS_RETRIES:
        return None
    if (getattr(response, "extensions", None) or {}).get("loci_transport") == b"grpc":
        return None
    delay = float(retries + 1)
    raw = str(response.headers.get("retry-after") or "").strip()
    if raw:
        try:
            delay = max(0.5, float(raw))
        except ValueError:
            pass  # HTTP 日期格式：按默认退避
    if delay > MAX_RETRY_AFTER_SECONDS:
        return None
    if budget is not None and delay >= budget:
        return None
    return delay


def _read_timeout(request: httpx2.Request) -> float | None:
    timeout = request.extensions.get("timeout")
    if isinstance(timeout, dict) and isinstance(timeout.get("read"), (int, float)):
        return float(timeout["read"])
    return None


class ConnectionRetryClient(httpx2.Client):
    def send(self, request: httpx2.Request, **kwargs: Any) -> httpx2.Response:
        # 重试单次模型请求，不重启 Agent，已执行的工具不会再次执行。
        connect_failures = 0
        status_retries = 0
        while True:
            try:
                response = super().send(request, **kwargs)
            except (httpx2.ConnectError, httpx2.ConnectTimeout):
                connect_failures += 1
                if connect_failures > 2:
                    raise
                logger.info("LLM 连接暂时失败，%s 秒后重试（%s/2）", connect_failures, connect_failures)
                time.sleep(connect_failures)
                continue
            delay = status_retry_delay(response, status_retries, budget=_read_timeout(request))
            if delay is None:
                record_http_protocol(response)
                return response
            status_retries += 1
            response.close()
            logger.info("LLM 上游返回 %s（忙碌/限流），%.1f 秒后重试（%s/%s）",
                        response.status_code, delay, status_retries, MAX_STATUS_RETRIES)
            time.sleep(delay)
