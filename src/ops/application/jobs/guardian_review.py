"""盘前计划、日复盘与周复盘；不调用任何交易撮合函数。"""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

from src.ledger import GuardianStore, PalaceStore
from src.market import calendar_trading_day
from src.shared.paths import palace_db
from src.ops.application.guardian_config import get_config
from src.ops.application.guardian_context import reference_days, strategy_sources, quant_reference_candidates, observe
from src.ops.application.guardian_decision import render_positions
from src.ops.application.guardian_review_agent import generate_review
from src.ops.application.guardian_review_data import build_review_facts, report_window, PERIOD_LABELS
from src.ops.application.guardian_review_format import report_body
from src.ops.application.guardian_review_digest import DIGEST_MAX_BYTES, notification_digest
from src.ops.application.jobs.context import JobContext, JobError, JobSkipped
from src.ops.application.notify import split_text_for_wecom
from src.ops.application.notify_dispatch import dispatch_text, ordered_delivery
from src.ops.application.notify_registry import get_channel_config


@ordered_delivery
def _notify(ledger: Any, store: Any, cfg: dict, period: str, day: str, result: dict) -> None:
    if not cfg["notify"]:
        if "notify" not in result:
            ledger.report_notification(period, day, {"success": False, "skipped": "disabled"})
        return
    if not ledger.claim_report_notification(period, day):
        return
    suffix = " · 更正" if result.get("revision", 1) > 1 else ""
    title = f"自主交易员 · {PERIOD_LABELS[period]}{suffix} · {day}"
    from src.ops.application.guardian_report_share import publish_report_share
    share_error = ""
    try:
        share_url = publish_report_share(ledger, period, day, result)
    except Exception as exc:
        share_url, share_error = "", str(exc)
    # Always rebuild the presentation from complete stored analysis, including old
    # revisions. The legacy body/notification_body may both contain long reports.
    budget = min(DIGEST_MAX_BYTES, 2048 - len(f'【{title}】\n'.encode('utf-8')))
    body = notification_digest(result['facts'], result['analysis'], share_url=share_url, limit_bytes=budget)
    chunks = [body]
    digest = sha256(body.encode('utf-8')).hexdigest()
    previous = (ledger.report(period, day) or {}).get('result', {}).get('notify', {})
    parts = dict(previous.get('parts', {})) if previous.get('body_sha256') == digest else {}
    progress = {'success': False, 'body_sha256': digest, 'total_parts': len(chunks), 'parts': parts,
                'share_url': share_url, 'share_error': share_error, 'format': 'digest_v2', 'body': body}
    webhook = str(get_channel_config(store, 'wecom').get('url') or '')
    for index, chunk in enumerate(chunks, 1):
        key = str(index)
        if parts.get(key, {}).get('success'):
            continue
        part_title = title
        wire_bytes = len(f'【{part_title}】\n{chunk}'.encode('utf-8'))
        if wire_bytes > 2048:
            raise JobError('报告分片含标题后超出企微字节上限，拒绝截断发送')
        try:
            receipt = (dispatch_text(store, title=part_title, body=chunk, webhook_override=webhook)
                       if webhook else {'success': False, 'errors': ['企微机器人未配置']})
        except Exception as exc:
            receipt = {'success': False, 'errors': [str(exc)]}
        parts[key] = {**receipt, 'bytes': wire_bytes}
        progress['sent_parts'] = sum(bool(p.get('success')) for p in parts.values())
        ledger.report_notification(period, day, progress, pending=bool(receipt.get('success')))
        if not receipt.get('success'):
            if receipt.get('skipped'):
                ledger.report_notification(period, day, {**progress, 'skipped': receipt['skipped']})
                return
            raise JobError(f"报告已生成，但第{index}/{len(chunks)}段通知未送达；后续从未成功段续传")
    progress.update(success=True, sent_parts=len(chunks), sent=sorted({c for p in parts.values() for c in p.get('sent', [])}))
    ledger.report_notification(period, day, progress)


def execute_guardian_review(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    store = context.ops_store
    if store is None:
        raise JobError("缺少运维库")
    cfg = get_config(store)
    if not cfg["enabled"]:
        raise JobSkipped("自主交易员未开启")
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    day = str(config.get("date") or now.date().isoformat())
    period = str(config.get("period") or "daily")
    try:
        if not calendar_trading_day(day):
            raise JobSkipped("交易所休市，静默跳过")
    except ValueError as exc:
        raise JobSkipped(str(exc)) from exc
    try:
        report_window(period, day, now)
    except LookupError as exc:
        raise JobSkipped(str(exc)) from exc
    with GuardianStore(context.palace_db) as ledger:
        existing = ledger.report(period, day)
        if existing and existing["status"] == "success":
            if period != "premarket":
                ledger.apply_close_valuation(existing["result"]["facts"]["account"], day)
            _notify(ledger, store, cfg, period, day, existing["result"])
            return {"report_key": existing["report_key"], "reused": True, "status": "success"}
        if period == 'weekly':
            daily = ledger.report('daily', day)
            if not daily or daily['status'] != 'success':
                raise JobSkipped('等待本周最后一个交易日的日复盘完成，再归集整周经验')
        token = ledger.claim_report(period, day)
        if token is None:
            raise JobSkipped("同一报告正在生成")
        try:
            with context.market() as market:
                facts = build_review_facts(ledger, market, period, day, now)
                facts["correction_reason"] = (existing or {}).get("result", {}).get("correction_reason", "")
                if day == now.date().isoformat():
                    with PalaceStore(context.palace_db or palace_db()) as palace:
                        reference = quant_reference_candidates(observe(palace, reference_days(facts["planning_trade_date"]), ledger.state(), []))
                    facts["strategy_reference_pool"] = [{"code": r["code"], "name": r["name"], "strategies": r["strategies"],
                        "signals": deepcopy(r["signals"])} for r in reference if r['signals']]
                    facts["reference_trading_days"] = reference_days(facts["planning_trade_date"])
                    facts["active_strategies"] = strategy_sources(store)
                    facts["reference_pool_as_of"] = now.isoformat()
                    facts["reference_pool_usage"] = "本次读取的参考池供后续计划，不用于重建日内时点信号；日内操作以cycles和trades为准。"
                    facts["evidence_ids"].extend(f"reference:{r['code']}" for r in reference)
            context.check_cancelled()
            analysis, usage, sources = generate_review(store, cfg, facts, check_cancelled=context.check_cancelled, palace_path=context.palace_db)
            codes = list(dict.fromkeys(p['code'] for p in [*analysis.get('plans', []), *analysis.get('stock_reviews', []), *analysis.get('watchlist_updates', [])]))
            if codes:
                with context.market() as market:
                    facts['stock_names'] = {code: row['name'] for code, row in market.instruments_meta(codes).items()}
            context.check_cancelled()
            if get_config(store) != cfg:
                raise ValueError("生成期间交易员设置已变更，报告作废")
            finished = datetime.now(ZoneInfo("Asia/Shanghai"))
            if period == "premarket":
                report_window(period, day, finished)
            result = {"status": "success", "facts": facts, "analysis": analysis, "usage": usage,
                      "revision": (existing or {}).get("result", {}).get("next_revision", 1),
                      "tool_evidence": sources, "created_at": finished.isoformat(),
                      "body": report_body(facts, analysis), "notification_body": notification_digest(facts, analysis)}
            ledger.finish_report(period, day, token, result)
        except Exception as exc:
            failure = {"status": "failed", "error": str(exc), "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                       "usage": getattr(exc, "usage", None),
                       "next_revision": (existing or {}).get("result", {}).get("next_revision", 1),
                       "correction_reason": (existing or {}).get("result", {}).get("correction_reason", ""),
                       "failure_notified": bool(existing and existing["result"].get("failure_notified"))}
            if cfg["notify"] and not failure["failure_notified"]:
                try:
                    body = render_positions(ledger.state()) + f"\n\n{day} {PERIOD_LABELS[period]}尚未完成：{exc}\n后续触发会重试。"
                    receipt = dispatch_text(store, title=f"自主交易员 · {PERIOD_LABELS[period]}异常", body=split_text_for_wecom(body, max_chunks=1)[0])
                    failure["failure_notify"] = receipt
                    failure["failure_notified"] = bool(receipt.get("success"))
                except Exception:
                    failure["failure_notified"] = False
            ledger.finish_report(period, day, token, failure)
            raise JobError(str(exc)) from exc
        if period != "premarket":
            ledger.apply_close_valuation(facts["account"], day)
        _notify(ledger, store, cfg, period, day, result)
        return {"report_key": f"{period}:{day}", "status": "success", "period": period,
                "period_pnl_cents": facts["period_pnl_cents"], "body": result["body"], "usage": usage}
