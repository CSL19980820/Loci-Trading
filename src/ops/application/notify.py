"""企业微信群机器人推送。

只走 webhook，不接企业自建应用。推送失败由调用方决定是否吞掉——
定时任务里推送不应拖垮主任务。

企微出站**只发 text**（msgtype=text），不用 markdown。
HTTP 经 ``notify_send_queue`` 串行：失败最多 3 次后再发下一条。
选股正文模板见 ``notify_screen_template``，可在系统推送联配置。
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

from src.ops.application.notify_screen_template import (
    format_pct,
    format_screen_picks_text,
    load_screen_template,
    normalize_screen_template,
    preview_screen_template,
    resolve_kind_tag,
)
from src.ops.application.notify_send_queue import NonRetryableSendError, run_serialized

logger = logging.getLogger(__name__)

WECOM_WEBHOOK_PREFIX = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key="
MAX_TEXT_CHARS = 2000

#: 企微 ``msgtype=text`` 的官方上限是 **2048 字节**（UTF-8），不是 2048 字。中文
#: 一字三字节，折算下来一条只装得下约 680 个汉字。``MAX_TEXT_CHARS`` 那道 2000
#: **字**的闸门对纯中文正文其实是 6000 字节——超限那部分能不能发出去取决于服务端
#: 心情，而它不会告诉你哪里被吞了。所以「长正文」必须**自己按字节分片**，别指望
#: `_clip`：截断是丢内容，分片是全都发到。
WECOM_TEXT_MAX_BYTES = 2048

#: 分片默认预算。留 ~240 字节给标题行与 ``（i/n）`` 标记。
WECOM_CHUNK_BYTES = 1800

__all__ = [
    "NotifyError",
    "NotifyNotRetryable",
    "WECOM_CHUNK_BYTES",
    "WECOM_TEXT_MAX_BYTES",
    "format_alerts",
    "format_digest",
    "format_job_status",
    "format_pct",
    "format_screen_picks_text",
    "format_screen_result",
    "format_sync_report",
    "load_screen_template",
    "mask_wecom_webhook",
    "normalize_screen_template",
    "preview_screen_template",
    "resolve_kind_tag",
    "send_wecom_markdown",
    "send_wecom_text",
    "split_text_for_wecom",
    "validate_wecom_webhook",
]


def _byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def split_text_for_wecom(
    text: str,
    *,
    limit_bytes: int = WECOM_CHUNK_BYTES,
    max_chunks: int = 6,
) -> list[str]:
    """把长正文按**字节**切成多片，优先在空行/换行/句末断开。

    为什么不按字数切：企微的上限是字节，中英混排时同样的字数可能差三倍字节。
    为什么优先在换行断：简报正文是分段的，从段落中间切开会把一句话劈成两条消息。

    ``max_chunks`` 是防呆闸门（一条简报最多几条消息）。真的超了就在最后一片尾部
    标注「已截断」——**明说被截断**比悄悄丢掉后半篇好。
    """
    body = str(text or "").strip()
    if not body:
        return []
    budget = max(64, min(int(limit_bytes), WECOM_TEXT_MAX_BYTES - 64))
    chunks: list[str] = []
    rest = body
    while rest and len(chunks) < max_chunks:
        if _byte_len(rest) <= budget:
            chunks.append(rest)
            rest = ""
            break
        cut = _cut_point(rest, budget)
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip("\n")
    if rest:
        tail = chunks[-1] if chunks else ""
        note = "\n…（后续已截断）"
        while tail and _byte_len(tail + note) > budget:
            tail = tail[:-1]
        chunks[-1] = tail + note
    return [chunk for chunk in chunks if chunk.strip()]


def _cut_point(text: str, budget: int) -> int:
    """在 ``budget`` 字节以内找一个体面的断点（字符下标）。"""
    # 先用字节预算换算出一个字符上界：UTF-8 下 1 字符 ≤ 4 字节，从 budget 往回收。
    high = min(len(text), budget)
    while high > 1 and _byte_len(text[:high]) > budget:
        high -= 1
    window = text[:high]
    for sep in ("\n\n", "\n", "。", "；", "！", "？", "，", " "):
        index = window.rfind(sep)
        # 太靠前的断点会切出一堆碎片：至少要用掉这一片的六成。
        if index >= high * 0.6:
            return index + len(sep)
    return high


class NotifyError(RuntimeError):
    """推送配置或发送失败。"""


class NotifyNotRetryable(NotifyError, NonRetryableSendError):
    """企微明确拒绝、且重试无意义（甚至有害）的失败。

    仍是 ``NotifyError`` 的子类——所有 ``except NotifyError`` 的调用点一行不用改；
    同时是 ``NonRetryableSendError``，出站队列见到它就不再重试。
    """


#: 收到这些 errcode 就别再打了。
#:
#: - ``45009`` 接口调用超过限制：官方对每个 webhook key 限 **20 条/分钟**。此前
#:   它被当成普通失败，``notify_send_queue`` 会在 1s 间隔内再打 2 次——在超频的
#:   伤口上撒盐，把「这一分钟满了」拖成「这个机器人被限得更久」。
#: - ``93000`` webhook 地址非法 / ``40001`` 凭证不合法 / ``93004`` 机器人已停用：
#:   配置问题，重试一万次也一样。
#:
#: 表外的错误码保持可重试：宁可多打两次，也不要把「网络抖了一下」误判成永久
#: 失败——静音的代价比重复出声大得多。
WECOM_NON_RETRYABLE_ERRCODES = frozenset({45009, 93000, 93004, 40001})


def _webhook_key(url: str) -> str:
    """取 webhook 的 key 段——官方限额按它算，不按机器人、不按租户。"""
    text = (url or "").strip()
    if text.startswith(WECOM_WEBHOOK_PREFIX):
        return text[len(WECOM_WEBHOOK_PREFIX) :]
    return text.rsplit("key=", 1)[-1] if "key=" in text else text


def validate_wecom_webhook(url: str) -> str:
    text = (url or "").strip()
    if not text:
        raise NotifyError("请填写企业微信群机器人 Webhook URL")
    if not text.startswith(WECOM_WEBHOOK_PREFIX):
        raise NotifyError(
            "Webhook 须以 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key= 开头"
        )
    key = text[len(WECOM_WEBHOOK_PREFIX) :]
    if len(key) < 8:
        raise NotifyError("Webhook key 无效")
    return text


def mask_wecom_webhook(url: str) -> str:
    text = (url or "").strip()
    if not text.startswith(WECOM_WEBHOOK_PREFIX):
        return ""
    key = text[len(WECOM_WEBHOOK_PREFIX) :]
    if len(key) <= 4:
        return WECOM_WEBHOOK_PREFIX + "****"
    return WECOM_WEBHOOK_PREFIX + "****" + key[-4:]


def send_wecom_text(webhook_url: str, content: str) -> dict[str, Any]:
    """企微唯一出站通道：text。经出站队列串行，失败最多 3 次。"""
    from src.ops.application.notify_calendar import notification_silence_reason
    silence = notification_silence_reason()
    if silence:
        return {"success": False, "skipped": silence}
    url = validate_wecom_webhook(webhook_url)
    body = json.dumps(
        {"msgtype": "text", "text": {"content": _clip(content, MAX_TEXT_CHARS)}},
        ensure_ascii=False,
    ).encode("utf-8")
   #: rate_key 让出站队列按 webhook key 过 20 条/分钟的令牌桶（官方口径）。
    return run_serialized(lambda: _post(url, body), rate_key=_webhook_key(url))


def send_wecom_markdown(webhook_url: str, content: str) -> dict[str, Any]:
    """兼容旧调用：内部仍转 text，避免误发 markdown。"""
    return send_wecom_text(webhook_url, content)


def _post(url: str, body: bytes) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise NotifyError(f"企微返回 HTTP {exc.code}：{detail}") from exc
    except TimeoutError as exc:
        raise NotifyError("无法连接企微 Webhook：timed out") from exc
    except urllib.error.URLError as exc:
        raise NotifyError(f"无法连接企微 Webhook：{exc.reason}") from exc
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise NotifyError(f"企微响应不是 JSON：{raw[:120]}") from exc
    errcode = int(payload.get("errcode", 0) or 0)
    if errcode != 0:
        detail = f"企微错误 {errcode}：{payload.get('errmsg', '')}"
        if errcode in WECOM_NON_RETRYABLE_ERRCODES:
            raise NotifyNotRetryable(detail)
        raise NotifyError(detail)
    return payload if isinstance(payload, dict) else {"ok": True}


def _clip(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 12] + "\n…(已截断)"


# ---- 其它推送模板 -----------------------------------------------------

def format_screen_result(
    result: dict[str, Any], *, template: dict[str, Any] | None = None
) -> str:
    """兼容旧名：默认按量化选股 text 模板。"""
    return format_screen_picks_text(result, kind_tag="量化", template=template)


def format_alerts(alerts: list[dict[str, Any]]) -> str:
    from src.review.application.alerts import ACTIONABLE_STATUSES

    actionable = [
        item for item in alerts if str(item.get("status") or "") in ACTIONABLE_STATUSES
    ]
    if not actionable:
        return "【触价提醒】\n今日暂无止损/目标触价。"
    lines = [f"【触价提醒】共 {len(actionable)} 条"]
    labels = {
        "stop_hit": "触及止损",
        "target_hit": "触及目标",
        "near_stop": "接近止损",
        "near_target": "接近目标",
    }
    for item in actionable[:12]:
        status = labels.get(str(item.get("status")), str(item.get("status")))
        name = item.get("name") or item.get("code")
        code = item.get("code")
        close = item.get("last_close")
        note = item.get("note") or ""
        close_text = f" 收盘 {close}" if close is not None else ""
        lines.append(f"{name} {code} · {status}{close_text}")
        if note:
            lines.append(f"  {note}")
    if len(actionable) > 12:
        lines.append(f"…另有 {len(actionable) - 12} 条")
    return "\n".join(lines)


def format_sync_report(result: dict[str, Any], *, job_name: str = "行情同步") -> str:
    failed = int(result.get("failed") or 0)
    lines = [
        f"【{job_name}】",
        (
            f"成功 {result.get('succeeded', 0)} · 跳过 {result.get('skipped', 0)} · "
            f"失败 {failed} · 写入 {result.get('rows_written', 0)} 行"
            f"（含当日 {result.get('spot_rows', 0)}）"
        ),
    ]
    failures = result.get("failures") or []
    for item in failures[:8]:
        lines.append(f"- {item}" if not isinstance(item, dict) else f"- {item}")
    return "\n".join(lines)


def format_digest(
    *,
    candidates: list[dict[str, Any]],
    summary: dict[str, Any] | None = None,
) -> str:
    """日终简报：当日候选池摘要。

    实盘账本（持仓 / 现金 / 当日盈亏）已下线，这里只转述候选池事实，不再报
    任何账户口径的金额。
    """
    stats = summary or {}
    as_of = ""
    for item in candidates:
        if isinstance(item, dict) and item.get("date"):
            as_of = str(item["date"])
            break
    lines = [
        "【日终简报】",
        f"截至 {as_of}" if as_of else "暂无候选记录",
        (
            f"候选精选 {stats.get('selected_count', '—')} · "
            f"未选 {stats.get('filtered_count', '—')} · 今日列表 {len(candidates)}"
        ),
    ]
    for card in (stats.get("picks") or [])[:8]:
        if not isinstance(card, dict):
            continue
        timing = f" · {card.get('timing')}" if card.get("timing") else ""
        lines.append(
            f"{card.get('name') or card.get('code')} {card.get('code')}"
            f" · {card.get('decision') or '精选'}{timing}"
        )
    return "\n".join(lines)


def format_job_status(
    *,
    job_name: str,
    kind: str,
    status: str,
    error: str = "",
    result: dict[str, Any] | None = None,
    template: dict[str, Any] | None = None,
) -> str:
    icon = "✓" if status == "success" else "✗"
    kind_labels = {
        "sync": "同步",
        "screen": "选股",
        "skill": "技能",
        "skill_watch": "监测",
        "strategy_monitor": "纸面监测",
        "intel_fetch": "情报采集",
        "intel_brief": "简报推送",
        "notify": "推送",
        "outcome": "跟踪",
        "backtest": "回测",
        "compare": "对比",
        "optimize": "优化",
        "prune": "清理",
    }
    status_labels = {
        "success": "成功",
        "failed": "失败",
        "running": "运行中",
        "skipped": "已跳过",
    }
    display_name = _display_job_name(job_name, kind)
    lines = [
        f"【任务{icon} {display_name}】",
        f"类型 {kind_labels.get(kind, kind)} · 状态 {status_labels.get(status, status)}",
    ]
    if error:
        lines.append(error[:200])
    tpl = template
    if status == "success" and kind == "screen" and isinstance(result, dict):
        return format_screen_picks_text(
            result,
            kind_tag=resolve_kind_tag("quant", tpl),
            title=_title_from_result(result, job_name),
            template=tpl,
        )
    if status == "success" and kind == "skill" and isinstance(result, dict) and result.get("picks"):
        return format_screen_picks_text(
            result,
            kind_tag=resolve_kind_tag("skills", tpl),
            title=_title_from_result(result, job_name),
            template=tpl,
        )
    if status == "failed" and kind == "sync" and isinstance(result, dict):
        return format_sync_report(result, job_name=job_name)
    if status == "failed" and kind == "sync":
        lines.append("行情同步失败，请到运维「执行历史」查看详情。")
    return "\n".join(lines)


def _display_job_name(job_name: str, kind: str) -> str:
    """失败/空结果通知也不把内部任务 slug 直接发给用户。"""
    raw = str(job_name or "").strip()
    for prefix in ("screen:", "skill:", "监测·"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    builtin_names = {
        "qianlong-close-v3": "潜龙出海（V3）",
        "qianfu-close": "潜伏（已下线）",
        "qianfu-1450": "潜伏（已下线）",
        "qianlong-tail-v1": "潜龙尾盘（已下线）",
        "rsi30-dip": "RSI22 次日低吸（已下线）",
        "sanyuan-tail-v1": "三源尾盘共振（15:30）",
        "yangshi-tail-v1": "杨氏尾盘选股（15:30）",
        "lugw-haidi": "海底捞月（已下线）",
    }
    from src.ops.application.skill_watch.watch_labels import WATCH_SLUG_LABELS

    builtin_names.update(WATCH_SLUG_LABELS)
    if raw in builtin_names:
        label = builtin_names[raw]
        return f"监测·{label}" if kind == "skill_watch" else label
    if kind == "skill_watch":
        from src.ops.application.skill_watch.watch_labels import watch_job_title

        return watch_job_title(slug=raw, job_name=job_name)
    if kind == "screen":
        return "选股"
    if kind == "skill":
        return "技能"
    # 仍含英文/连字符的内部名，不直接外露
    if re.search(r"[A-Za-z]", raw) and ("-" in raw or "_" in raw):
        return kind_labels_fallback(kind)
    return raw or "任务"


def kind_labels_fallback(kind: str) -> str:
    return {
        "sync": "同步",
        "screen": "选股",
        "skill": "技能",
        "skill_watch": "监测",
        "strategy_monitor": "纸面监测",
        "intel_fetch": "情报采集",
        "intel_brief": "简报推送",
        "notify": "推送",
    }.get(kind, "任务")


def _title_from_result(result: dict[str, Any], fallback: str) -> str:
    raw = (
        result.get("skill_name")
        or result.get("strategy")
        or result.get("skill")
        or fallback
        or "选股"
    )
    name = str(raw).strip()
    if name.startswith("screen:"):
        name = name[len("screen:") :]
    return name


# ---- 多通道告警（实现在 notify_registry / infrastructure.notify_channels）----
#
# 在这里再导一次，是为了让「推送相关的东西从 src.ops.application.notify 拿」
# 这个既有心智继续成立。实现不放本文件：本文件已 339 行，且企微出站与
# 通道注册表是两件事，混在一起下一个人就分不清改哪儿了。
from src.ops.application.notify_registry import (  # noqa: E402
    NotifyChannelError,
    dispatch,
    get_channel_config,
    list_channels,
    save_channel_config,
    test_channel,
)

__all__ += [
    "NotifyChannelError",
    "dispatch",
    "get_channel_config",
    "list_channels",
    "save_channel_config",
    "test_channel",
]
