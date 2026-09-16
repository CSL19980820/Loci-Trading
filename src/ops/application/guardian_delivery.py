"""Deliver saved notices independently of decision generation and settlement."""
from __future__ import annotations

import json
from typing import Any

from src.ops.application.guardian_delivery_channels import default_targets
from src.ops.application.guardian_delivery_parts import NoticeLeaseLost, send_notice_parts


def _summarize(receipt: dict[str, Any], attempt: int) -> None:
    targets = receipt["channel_targets"]
    channels = receipt["channel_receipts"]
    pending = [key for key in targets if not channels.get(key, {}).get("success")]
    sent = sorted({target["type"] for key, target in targets.items() if key not in pending})
    errors = []
    suppressed = []
    skips = []
    for key in pending:
        result = channels.get(key, {})
        errors.extend(result.get("errors") or [])
        if result.get("error"):
            errors.append(result["error"])
        suppressed.extend(result.get("suppressed") or [])
        if result.get("skipped"):
            skips.append(result["skipped"])
    receipt.pop("error", None)
    receipt.pop("skipped", None)
    receipt.update(success=bool(targets) and not pending, partial=bool(pending) and (bool(sent) or any(r.get("partial") for r in channels.values())),
                   sent=sent, errors=errors, suppressed=sorted(set(suppressed)),
                   delivery_attempt=attempt)
    if pending and len(skips) == len(pending) and len(set(skips)) == 1:
        receipt["skipped"] = skips[0]


def _deliver_notice(ledger: Any, store: Any, send: Any, notice: dict[str, Any],
                    receipt: dict[str, Any]) -> bool:
    if not receipt.get("channel_targets"):
        targets = default_targets(store)
        if not targets:
            # Preserve the normal unconfigured-channel receipt and injected senders.
            def progress(value: dict) -> bool:
                receipt.update(value)
                return ledger.record_notice_progress(notice["slot"], notice["attempts"], receipt)
            try:
                result = send_notice_parts(store, send, None, title=notice["title"], body=notice["body"],
                                           previous=receipt, checkpoint=progress)
            except NoticeLeaseLost:
                return False
            receipt.update(result)
            return True
        receipt["channel_targets"] = targets
        receipt["channel_receipts"] = {}
        # Older aggregate receipts identify types, not IDs. Import only unambiguous facts.
        for name in receipt.get("sent") or []:
            keys = [key for key, target in targets.items() if target["type"] == name]
            for key in keys:
                receipt["channel_receipts"][key] = (
                    {"success": True, "sent": [name]} if len(keys) == 1 else
                    {"success": False, "skipped": "ambiguous_legacy_receipt", "sent": []})
    for key, target in receipt["channel_targets"].items():
        previous = receipt["channel_receipts"].get(key, {})
        if previous.get("success") or previous.get("skipped") == "ambiguous_legacy_receipt":
            continue
        _summarize(receipt, notice["attempts"])
        if not ledger.record_notice_progress(notice["slot"], notice["attempts"], receipt):
            return False
        try:
            def progress(value: dict) -> bool:
                receipt["channel_receipts"][key] = value
                _summarize(receipt, notice["attempts"])
                return ledger.record_notice_progress(notice["slot"], notice["attempts"], receipt)
            result = send_notice_parts(store, send, target, title=notice["title"], body=notice["body"],
                                       previous=previous, checkpoint=progress)
        except NoticeLeaseLost:
            return False
        except Exception as exc:
            result = {"success": False, "errors": [str(exc)], "sent": []}
        receipt["channel_receipts"][key] = result
        _summarize(receipt, notice["attempts"])
        # Checkpoint each response before the next external side effect.
        if not ledger.record_notice_progress(notice["slot"], notice["attempts"], receipt):
            return False
    _summarize(receipt, notice["attempts"])
    return True


def deliver_pending(ledger: Any, store: Any, send: Any) -> dict[str, dict]:
    receipts = {}
    for notice in ledger.claim_notices():
        receipt = json.loads(notice["receipt_json"])
        try:
            owned = ledger.record_notice_progress(notice["slot"], notice["attempts"], receipt)
            if owned:
                owned = _deliver_notice(ledger, store, send, notice, receipt)
        except Exception as exc:
            receipt.update(success=False, errors=[str(exc)])
            owned = True
        receipt["delivery_attempt"] = notice["attempts"]
        if not owned or not ledger.finish_notice(notice["slot"], notice["attempts"], receipt):
            receipt.update(success=False, skipped="lease_lost")
        receipts[notice["slot"]] = receipt
    return receipts
