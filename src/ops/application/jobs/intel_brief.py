"""``intel_brief`` 任务：把悟道 AI 简报转成纯文本推到企微。

## 为什么是一个独立 kind，而不是 ``notify`` 的一个模板

``notify`` 的模板读的是**本仓自己的**运行结果（触价、候选池、同步回执）。这一条
要先出网取数（悟道 ``briefings``）、要判「今天这一档生成了没有」、要防重、还要
按字节分片发好几条——这些都是 ``execute_notify`` 里没有的语义。塞进模板参数只会
让那个函数变成第二个调度器。

## 三条不变量

1. **悟道没配 / 不可用 → ``skipped``，不是失败**（可选依赖铁律）。
2. **这一档还没生成 → ``skipped``**。悟道侧 09:00 / 12:00 / 15:30 / 21:00 出稿，
   我们刻意比它晚 10 分钟触发，并且**一个档位挂多个触发点**（见
   ``ensure_intel_brief_jobs``）：09:10 没出就 09:25 再看一眼，出了再推。
   把「还没出」记成 failed，运维页每天会多四个红叉，而什么都没坏。
3. **同一档同一天只推一次**：防重键带上悟道的 ``generatedAt``，所以它重算过一次
   （内容真的变了）允许再推一条，重复触发不会。复用选股那套 ``wecom_push_marks``。

## 简报是旁注，不是账

正文首行固定标注「悟道 AI 生成，仅作旁注」，且**不入库、不参与复盘数字**。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from src.ops.application.jobs.context import JobContext

logger = logging.getLogger(__name__)

#: 简报一天四档、每档最多几个触发点，缓存 TTL 只要能覆盖「同一档的重试」就够。
#: 给 20 分钟：09:10 真调一次，09:25 那次若已推过会被防重拦掉，不会白扣配额。
_CACHE_MAX_AGE_MINUTES = 20

#: 一条简报最多切几片。开盘档实测 8.3KB / 1800 字节 ≈ 5 片；给 6 片的余量。
#: 配置键 ``max_chunks`` 可调，调小就是「只发前面几段」（尾部会明写已截断）。
DEFAULT_MAX_CHUNKS = 6
#: 分片发送间隔（秒）。企微等 webhook 服务端在毫秒级连续并发接收消息时，
#: 群聊展示顺序可能由于网络抖动或服务端落库时序颠倒。
#: 串行分片之间引入微小间隔（默认 1.0s），确保消息严格按顺序落库与渲染。
DEFAULT_CHUNK_INTERVAL_SEC = 1.0


def execute_intel_brief(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """取一档悟道简报 → 纯文本 → 分片推企微。悟道未装配或简报未生成时软跳过。"""
    from src.intel import wudao_availability
    from src.intel.application.briefing import (
        briefing_body_text,
        briefing_header,
        fetch_briefing_payload,
        parse_briefing,
        resolve_slot,
        slot_label,
    )
    from src.ops.application.jobs.intel_fetch import resolve_pool
    from src.ops.application.notify import split_text_for_wecom
    from src.ops.application.notify_dispatch import dispatch_text
    from src.ops.application.wecom_push_mark import (
        is_screen_pushed,
        mark_screen_pushed,
        shanghai_today,
    )

    slot = resolve_slot(config.get("slot") or config.get("type"))
    label = slot_label(slot)
    server = str(config.get("server") or "wudao").strip() or "wudao"
    pool = resolve_pool(config.get("pool"))
    push = bool(config.get("push_wecom", True))
    prefer_full = bool(config.get("full_text", True))
    max_chunks = max(1, min(int(config.get("max_chunks") or DEFAULT_MAX_CHUNKS), 10))
    day = shanghai_today()
    base = {"slot": slot, "label": label, "server": server, "pool": pool, "trade_date": day}

    availability = wudao_availability()
    if not availability.get("available"):
        reason = str(availability.get("reason") or "悟道 MCP 不可用")
        logger.info("intel_brief 软跳过：%s", reason)
        return {
            **base,
            "skipped": True,
            "reason": "mcp_unavailable",
            "unavailable_reason": reason,
            "summary": f"悟道未装配，{label}推送已跳过：{reason}",
        }

    try:
        with context.market() as store:
            payload = fetch_briefing_payload(
                slot=slot,
                server=server,
                trade_date=day,
                market_store=store,
                pool=pool,
                cache=True,
                cache_max_age_minutes=_CACHE_MAX_AGE_MINUTES,
            )
    except Exception as exc:  # noqa: BLE001 — 取数失败不该把调度刷红
        logger.warning("intel_brief 取数失败：%s", exc)
        return {
            **base,
            "skipped": True,
            "reason": "fetch_failed",
            "error": str(exc),
            "summary": f"{label}取数失败（已跳过）：{exc}",
        }

    if payload.get("unavailable"):
        reason = str(payload.get("unavailable_reason") or "悟道 MCP 不可用")
        return {
            **base,
            "skipped": True,
            "reason": "mcp_unavailable",
            "unavailable_reason": reason,
            "summary": f"悟道不可用，{label}推送已跳过：{reason}",
        }

    doc = parse_briefing(payload, slot=slot)
    if doc is not None and prefer_full and not doc.full_text and payload.get("cached"):
        # 缓存里那一份可能是**别的入口**（或旧版本代码）用 `format!=json` 抓的：
        # `format` 是纯传输参数，不进复用键（`intel_cache._TRANSPORT_ARGS`），而全文只在
        # JSON 正文里。回源一次再解一遍——把 410 字的摘要兜底当成简报发出去，是「静默降级」，
        # 比多花一次配额糟得多。
        logger.info("intel_brief 缓存命中但无全文，回源一次：%s", slot)
        try:
            with context.market() as store:
                fresh = fetch_briefing_payload(
                    slot=slot,
                    server=server,
                    trade_date=day,
                    market_store=store,
                    pool=pool,
                    cache=False,
                )
        except Exception as exc:  # noqa: BLE001 — 回源失败就用摘要，不改结论
            logger.warning("intel_brief 全文回源失败（用摘要继续）：%s", exc)
        else:
            refreshed = parse_briefing(fresh, slot=slot)
            if refreshed is not None and refreshed.full_text:
                payload, doc = fresh, refreshed
    if doc is None:
        # 「还没出稿」和「取回来是错误」在这里同义：都不该推、都不该记失败。
        return {
            **base,
            "skipped": True,
            "reason": "not_published",
            "cached": bool(payload.get("cached")),
            "summary": f"{label}尚未生成（悟道侧未出稿），等下一个触发点再看",
        }

    if doc.date and day and doc.date != day:
        # 悟道在非交易日会把上一份简报当「最新」返回：推出去就是拿昨天的稿冒充今天。
        return {
            **base,
            "skipped": True,
            "reason": "stale_briefing",
            "briefing_date": doc.date,
            "summary": f"{label}最新一份是 {doc.date} 的，非当日不推",
        }

    body = briefing_body_text(doc, prefer_full=prefer_full)
    header = briefing_header(doc)
    chunks = split_text_for_wecom(body, max_chunks=max_chunks)
    result: dict[str, Any] = {
        **base,
        "briefing_date": doc.date,
        "briefing_time": doc.time,
        "generated_at": doc.generated_at,
        "fingerprint": doc.fingerprint,
        "chars": len(body),
        "bytes": len(body.encode("utf-8")),
        "chunks": len(chunks),
        "cached": bool(payload.get("cached")),
        "full_text_used": bool(prefer_full and doc.full_text),
    }
    if not chunks:
        return {**result, "skipped": True, "reason": "empty_body", "summary": f"{label}正文为空，不推"}
    if not push:
        return {
            **result,
            "pushed": False,
            "push_skipped": "push_disabled",
            "summary": f"{label}已取回（{len(body)} 字），推送开关关闭",
        }

    store_ops = context.ops_store
    job_id = str(context.job_id or f"intel_brief:{slot}")
    if store_ops is not None and is_screen_pushed(
        store_ops, job_id=job_id, day=day, fingerprint=doc.fingerprint
    ):
        return {
            **result,
            "skipped": True,
            "reason": "already_pushed",
            "summary": f"{label}今天这一版已推过（{doc.fingerprint}）",
        }

    sent = 0
    errors: list[str] = []
    skipped_reason = ""
    total = len(chunks)
    interval = float(
        config.get("chunk_interval_sec", DEFAULT_CHUNK_INTERVAL_SEC)
        if config.get("chunk_interval_sec") is not None
        else DEFAULT_CHUNK_INTERVAL_SEC
    )
    from src.ops.application.notify_dispatch import delivery_lock
    with delivery_lock:
        for index, chunk in enumerate(chunks, start=1):
            if index > 1 and interval > 0:
                time.sleep(interval)
            marker = f"（{index}/{total}）" if total > 1 else ""
            outcome = dispatch_text(
                store_ops,
                title=f"{label}·悟道",
                body=f"{header}{marker}\n{chunk}",
                prepend_title_to_wecom=False,
                bypass_quiet=bool(config.get("bypass_quiet")),
            )
            if outcome.get("skipped"):
                skipped_reason = str(outcome.get("skipped"))
                break
            if outcome.get("sent"):
                sent += 1
            errors.extend(str(message) for message in outcome.get("errors") or [])
            if outcome.get("error"):
                errors.append(str(outcome["error"]))
            if not outcome.get("success"):
                break

    if sent == total and not errors and store_ops is not None:
        mark_screen_pushed(
            store_ops,
            job_id=job_id,
            day=day,
            fingerprint=doc.fingerprint,
            meta={"slot": slot, "chunks": total, "sent": sent},
        )
    if not sent and skipped_reason:
        # quiet_hours / rate_limited 是刻意没发，不是故障（晚间档 21:10 常撞安静时段）。
        return {
            **result,
            "skipped": True,
            "reason": skipped_reason,
            "summary": f"{label}未推送：{skipped_reason}",
        }
    if sent < total or errors:
        detail = "；".join(errors) or "没有可用的通知渠道"
        return {
            **result,
            "pushed": False,
            "push_error": detail,
            "summary": f"{label}推送失败：{detail}",
        }
    return {
        **result,
        "pushed": True,
        "sent_chunks": sent,
        "errors": errors,
        "summary": f"{label}已推企微：{sent}/{total} 条，共 {len(body)} 字",
    }


__all__ = ["DEFAULT_CHUNK_INTERVAL_SEC", "DEFAULT_MAX_CHUNKS", "execute_intel_brief"]
