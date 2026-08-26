"""Agent Bearer（PALACE_WRITE_TOKEN）策略：生产最小长度 + 轮换提示，无内置 TTL。"""
from __future__ import annotations

from datetime import datetime, timezone
import logging

WRITE_TOKEN_ROTATION_HINT_DAYS = 90
# 生产环境若配置 Bearer，长度须 ≥ 该值（本地桌面不强制）。
WRITE_TOKEN_MIN_LENGTH_PRODUCTION = 32


def apply_write_token_policy(
    *,
    write_token: str,
    is_production: bool,
    require_write_auth: bool,
    issued_at_raw: str,
    log: logging.Logger | None = None,
) -> list[str]:
    """校验/提示写令牌策略；返回已记录消息（便于测试）。过短生产令牌抛 RuntimeError。"""
    logger = log or logging.getLogger(__name__)
    messages: list[str] = []
    token = (write_token or "").strip()
    issued_raw = (issued_at_raw or "").strip()

    if token and is_production:
        if len(token) < WRITE_TOKEN_MIN_LENGTH_PRODUCTION:
            raise RuntimeError(
                "生产环境 PALACE_WRITE_TOKEN 长度须 ≥"
                f"{WRITE_TOKEN_MIN_LENGTH_PRODUCTION}（高熵随机串）；请轮换后重启"
            )
        msg = (
            "PALACE_WRITE_TOKEN 已配置：Agent Bearer 为长期静态密钥，无内置过期。"
            "生产环境优先浏览器会话；请定期轮换，并可用 PALACE_WRITE_TOKEN_ISSUED_AT=YYYY-MM-DD 触发启动告警"
        )
        logger.warning(msg)
        messages.append(msg)
    elif require_write_auth and is_production and not token:
        msg = "未配置 PALACE_WRITE_TOKEN：无浏览器会话时 Agent 无法 Bearer 写入"
        logger.info(msg)
        messages.append(msg)

    if token and issued_raw:
        try:
            issued = datetime.fromisoformat(issued_raw.replace("Z", "+00:00"))
            if issued.tzinfo is None:
                issued = issued.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - issued.astimezone(timezone.utc)).days
            if age_days > WRITE_TOKEN_ROTATION_HINT_DAYS:
                msg = (
                    f"Agent Bearer 已签发 {age_days} 天"
                    f"（建议阈值 {WRITE_TOKEN_ROTATION_HINT_DAYS}），请轮换 PALACE_WRITE_TOKEN"
                )
                logger.warning(msg)
                messages.append(msg)
        except ValueError:
            msg = "PALACE_WRITE_TOKEN_ISSUED_AT 无法解析，忽略轮换提示"
            logger.warning(msg)
            messages.append(msg)

    return messages
