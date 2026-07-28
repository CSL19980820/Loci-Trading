"""企业微信群机器人推送。

只走 webhook，不接企业自建应用。推送失败由调用方决定是否吞掉——
定时任务里推送不应拖垮主任务。
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

WECOM_WEBHOOK_PREFIX = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key="
MAX_MARKDOWN_CHARS = 3500


class NotifyError(RuntimeError):
    """推送配置或发送失败。"""


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


def send_wecom_markdown(webhook_url: str, content: str) -> dict[str, Any]:
    url = validate_wecom_webhook(webhook_url)
    body = json.dumps(
        {"msgtype": "markdown", "markdown": {"content": _clip(content)}},
        ensure_ascii=False,
    ).encode("utf-8")
    return _post(url, body)


def send_wecom_text(webhook_url: str, content: str) -> dict[str, Any]:
    url = validate_wecom_webhook(webhook_url)
    body = json.dumps(
        {"msgtype": "text", "text": {"content": _clip(content, 2000)}},
        ensure_ascii=False,
    ).encode("utf-8")
    return _post(url, body)


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
    except urllib.error.URLError as exc:
        raise NotifyError(f"无法连接企微 Webhook：{exc.reason}") from exc
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise NotifyError(f"企微响应不是 JSON：{raw[:120]}") from exc
    if int(payload.get("errcode", 0)) != 0:
        raise NotifyError(f"企微错误 {payload.get('errcode')}：{payload.get('errmsg', '')}")
    return payload if isinstance(payload, dict) else {"ok": True}


def _clip(text: str, limit: int = MAX_MARKDOWN_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 12] + "\n…(已截断)"


# ---- 模板 -------------------------------------------------------------

def format_alerts(alerts: list[dict[str, Any]]) -> str:
    from src.review.application.alerts import ACTIONABLE_STATUSES

    actionable = [
        item for item in alerts if str(item.get("status") or "") in ACTIONABLE_STATUSES
    ]
    if not actionable:
        return "### 触价提醒\n今日暂无止损/目标触价。"
    lines = [f"### 触价提醒（{len(actionable)}）"]
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
        lines.append(f"- **{name}** `{code}` · {status}{close_text}")
        if note:
            lines.append(f"  {note}")
    if len(actionable) > 12:
        lines.append(f"…另有 {len(actionable) - 12} 条")
    return "\n".join(lines)


def format_screen_result(result: dict[str, Any]) -> str:
    strategy = result.get("strategy") or "选股"
    trade_date = result.get("trade_date") or ""
    picks = result.get("picks") or []
    lines = [f"### 选股结果 · {strategy}", f"日期 {trade_date} · 入选 {len(picks)}"]
    reason = result.get("ai_reason") or result.get("reason")
    if reason:
        lines.append(f"> {reason}")
    for pick in picks[:15]:
        if not isinstance(pick, dict):
            continue
        name = pick.get("name") or ""
        code = pick.get("code") or ""
        score = pick.get("score")
        score_text = f" · 分 {score}" if score is not None else ""
        lines.append(f"- **{name or code}** `{code}`{score_text}")
    if len(picks) > 15:
        lines.append(f"…另有 {len(picks) - 15} 只")
    return "\n".join(lines)


def format_sync_report(result: dict[str, Any], *, job_name: str = "行情同步") -> str:
    failed = int(result.get("failed") or 0)
    lines = [
        f"### {job_name}",
        (
            f"成功 {result.get('succeeded', 0)} · 跳过 {result.get('skipped', 0)} · "
            f"失败 **{failed}** · 写入 {result.get('rows_written', 0)} 行"
            f"（含当日 {result.get('spot_rows', 0)}）"
        ),
    ]
    failures = result.get("failures") or []
    for item in failures[:8]:
        lines.append(f"- `{item}`" if not isinstance(item, dict) else f"- {item}")
    return "\n".join(lines)


def format_digest(dashboard: dict[str, Any]) -> str:
    account = dashboard.get("account") or {}
    positions = dashboard.get("positions") or []
    candidates = dashboard.get("candidates") or []
    summary = dashboard.get("candidate_summary") or {}
    as_of = dashboard.get("as_of") or ""
    realized = account.get("realized_pnl")
    today = account.get("today_realized_pnl")
    assets = account.get("total_assets")

    def money(value: Any) -> str:
        if value is None:
            return "—"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "—"
        sign = "+" if number > 0 else ""
        return f"{sign}{number:,.2f}"

    lines = [
        "### 日终简报",
        f"截至 {as_of}",
        f"- 累计已实现 {money(realized)} · 当日 {money(today)}",
        f"- 总资产 {money(assets)} · 持仓 {len(positions)} 只",
        (
            f"- 候选精选 {summary.get('selected', '—')} · "
            f"观察 {summary.get('watch', '—')} · 今日列表 {len(candidates)}"
        ),
    ]
    for pos in positions[:8]:
        if not isinstance(pos, dict):
            continue
        lines.append(
            f"- {pos.get('name') or pos.get('code')} `{pos.get('code')}` "
            f"{pos.get('shares')} 股 @ {pos.get('cost')}"
        )
    return "\n".join(lines)


def format_job_status(
    *,
    job_name: str,
    kind: str,
    status: str,
    error: str = "",
    result: dict[str, Any] | None = None,
) -> str:
    icon = "✓" if status == "success" else "✗"
    lines = [f"### 任务{icon} {job_name}", f"类型 `{kind}` · 状态 **{status}**"]
    if error:
        lines.append(f"> {error[:200]}")
    if status == "success" and kind == "screen" and isinstance(result, dict):
        return format_screen_result(result)
    if status == "failed" and kind == "sync" and isinstance(result, dict):
        return format_sync_report(result, job_name=job_name)
    if status == "failed" and kind == "sync":
        lines.append("行情同步失败，请到运维「执行历史」查看详情。")
    return "\n".join(lines)
