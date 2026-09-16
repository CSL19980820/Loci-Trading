"""只重试发送前的连接失败，保留 Client 的代理、证书和流式行为。"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx2

logger = logging.getLogger(__name__)


class ConnectionRetryClient(httpx2.Client):
    def send(self, request: httpx2.Request, **kwargs: Any) -> httpx2.Response:
        # ConnectError/ConnectTimeout 尚未发送业务请求；读写失败和已开始的流不能重放。
        # 重试单次模型请求，不重启 Agent，已执行的工具不会再次执行。
        for attempt in range(3):
            try:
                return super().send(request, **kwargs)
            except (httpx2.ConnectError, httpx2.ConnectTimeout):
                if attempt == 2:
                    raise
                delay = attempt + 1
                logger.info("LLM 连接暂时失败，%s 秒后重试（%s/2）", delay, attempt + 1)
                time.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover
