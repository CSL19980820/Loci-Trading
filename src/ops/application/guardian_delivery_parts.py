"""Full guardian notices with durable per-target, per-part delivery receipts."""
from __future__ import annotations

from hashlib import sha256
import time
from typing import Any, Callable

from src.ops.application.guardian_delivery_channels import send_target
from src.ops.application.notify import split_text_for_wecom
from src.ops.application.notify_dispatch import ordered_delivery


class NoticeLeaseLost(RuntimeError):
    """Stop external sends when another delivery worker owns the notice."""


def notice_parts(title: str, body: str) -> list[tuple[str, str]]:
    """Reserve title/sequence bytes without dropping any content-bearing fragment."""
    if len(f"【{title}】\n{body}".encode("utf-8")) <= 2000:
        return [(title, body)]
    digits = len(str(max(1, len(body))))
    overhead = len(f"【{title}（{'9' * digits}/{'9' * digits}）】\n".encode("utf-8"))
    budget = min(1700, 2000 - overhead)
    if budget < 64:
        raise ValueError("通知标题过长，无法在通道字节限制内完整分段")
    chunks = split_text_for_wecom(body, limit_bytes=budget, max_chunks=max(1, len(body)))
    parts = [(f"{title}（{i}/{len(chunks)}）", chunk) for i, chunk in enumerate(chunks, 1)]
    if any(len(f"【{part_title}】\n{chunk}".encode("utf-8")) > 2000 for part_title, chunk in parts):
        raise ValueError("通知分段超过通道字节限制，未截断发送")
    return parts


@ordered_delivery
def send_notice_parts(
    store: Any, send: Any, target: dict[str, str] | None, *, title: str, body: str,
    previous: dict[str, Any], checkpoint: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    parts = notice_parts(title, body)
    if len(parts) == 1:
        return send_target(store, send, target, title=title, body=body) if target else send(store, title=title, body=body)
    digest = sha256((title + "\n" + body).encode("utf-8")).hexdigest()
    if previous.get("body_sha256") not in (None, digest):
        raise ValueError("待发通知与已保存分段不一致，拒绝重新发送已确认内容")
    receipts = dict(previous.get("parts") or {})
    result = {"success": False, "body_sha256": digest, "total_parts": len(parts), "parts": receipts,
              "sent": [], "errors": []}
    for index, (part_title, chunk) in enumerate(parts, 1):
        key = str(index)
        if receipts.get(key, {}).get("success"):
            continue
        result["sent_parts"] = sum(bool(r.get("success")) for r in receipts.values())
        if not checkpoint(result):
            raise NoticeLeaseLost("通知租约已失效，停止后续分段")
        if index > 1:
            time.sleep(1.5)
        try:
            receipt = (send_target(store, send, target, title=part_title, body=chunk)
                       if target else send(store, title=part_title, body=chunk))
        except Exception as exc:
            receipt = {"success": False, "sent": [], "errors": [str(exc)]}
        receipts[key] = receipt
        result["sent_parts"] = sum(bool(r.get("success")) for r in receipts.values())
        result["partial"] = result["sent_parts"] > 0
        if not receipt.get("success"):
            result.update(errors=receipt.get("errors") or [], sent=[])
            if receipt.get("skipped"):
                result["skipped"] = receipt["skipped"]
        if not checkpoint(result):
            raise NoticeLeaseLost("通知租约已失效，停止后续分段")
        if not receipt.get("success"):
            return result
    result.update(success=True, partial=False, sent_parts=len(parts),
                  sent=sorted({name for receipt in receipts.values() for name in receipt.get("sent", [])}))
    return result
