"""独立智能体的简讯；已落账研究与通知成败分别保存。"""
import re
from hashlib import sha256

from src.ledger import StockAgentStore
from src.ops.application.guardian_notification import format_notification_time
from src.ops.application.notify_dispatch import dispatch_text, ordered_delivery
from src.ops.application.notify import split_text_for_wecom
from src.ops.application.stock_agent_report_share import publish_stock_agent_share
from src.ops.application.notify_registry import get_channel_config
from src.ops.application.stock_agent_prompts import PHASE_NAMES


def execution_brief(detail: dict) -> str:
    """盘中通知只复述已提交回执，不让模型的意图冒充成交。"""
    lines = []
    labels = {"buy": "买入", "add": "加仓", "sell": "卖出", "reduce": "减仓",
              "stop_loss": "止损", "take_profit": "止盈"}
    for fill in detail.get("fills", []):
        label = labels.get(fill.get("action"), "卖出" if fill.get("side") == "sell" else "买入")
        lines.append(f"模拟{label}：{fill.get('name') or fill['code']}({fill['code']}) "
                     f"{fill['quantity']}股 × {fill['price_cents']/100:.2f}元，余{fill['after_quantity']}股。")
    for rejected in detail.get("rejects", []):
        lines.append(f"未成交：{rejected.get('name') or rejected.get('code')}，{rejected.get('reason', '执行校验未通过')}。")
    if not lines:
        lines.append("本轮无成交。")
    if len(lines) > 5:
        lines = lines[:4] + [f"本轮模拟成交{len(detail.get('fills', []))}笔，其余回执见日记。"]
    return "\n".join(lines)


@ordered_delivery
def notify_stock_agent(store, path: str, agent_id: str, run_id: str) -> dict:
    with StockAgentStore(path) as ledger:
        run = ledger.run_detail(agent_id, run_id)
        profile = ledger.get(agent_id)
        detail = run["detail"]
        previous = detail.get("notify") or {}
        if previous.get("success"):
            return previous
        phase = run["phase"]
        if phase not in {"premarket", "auction", "review"} and not detail.get("fills"):
            return {"success": False, "skipped": "no_action"}
        summary = str(detail.get("summary") or run.get("summary") or "本轮研究已完成。")
        summary = re.sub(r"\[([^\]]+)\]\(https?://[^\s)]+\)", r"\1", summary)
        summary = re.sub(r"(?m)^#{1,6}\s+", "", summary).replace("**", "").replace("`", "")
        # 旧运行仍可能保存长报告。补发只取开头完整句，全文保留在日记。
        if len(summary) > 300:
            head = summary[:280]
            end = max(head.rfind("。"), head.rfind("；"), head.rfind("\n"))
            summary = (head[:end + 1] if end > 80 else head) + "\n完整研究见智能体日记。"
        if phase in {"intraday", "closeout"}:
            summary = execution_brief(detail)
        share_url = publish_stock_agent_share(ledger, agent_id, run_id, profile, run, summary)
        if share_url:
            summary += f"\n\n查看完整报告（免登录）：\n{share_url}"
        title = f"{profile['config']['name']} · {PHASE_NAMES[phase]} · {format_notification_time(detail.get('as_of') or run.get('finished_at') or run['started_at'])}"
        webhook = str(get_channel_config(store, "wecom").get("url") or "")
        chunks = split_text_for_wecom(summary, limit_bytes=1700, max_chunks=max(1, len(summary)))
        digest = sha256(summary.encode()).hexdigest()
        parts = dict(previous.get('parts', {})) if previous.get('body_sha256') == digest else {}
        receipt = {'success': True, 'sent': []}
        for index, chunk in enumerate(chunks, 1):
            key = str(index)
            if parts.get(key, {}).get('success'):
                continue
            part_title = title if len(chunks) == 1 else f"{title}（{index}/{len(chunks)}）"
            try:
                receipt = (dispatch_text(store, title=part_title, body=chunk, webhook_override=webhook)
                           if webhook else {"success": False, "errors": ["企微机器人未配置"]})
            except Exception as exc:
                receipt = {"success": False, "errors": [str(exc)]}
            parts[key] = receipt
            if not receipt.get('success'):
                break
        receipt = {**receipt, "success": len(parts) == len(chunks) and all(p.get('success') for p in parts.values()),
                   "sent": sorted({name for p in parts.values() for name in p.get('sent', [])}),
                   "title": title, "body": summary, "share_url": share_url, "parts": parts, "body_sha256": digest}
        ledger.save_notification(agent_id, run_id, receipt)
        return receipt
