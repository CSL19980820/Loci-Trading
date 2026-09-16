"""Long execution notices are complete and can resume without repeating saved parts."""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from src.ledger import GuardianStore
from src.ops.infrastructure.store import OpsStore
from src.ops.application.guardian_delivery import deliver_pending
from src.ops.application.guardian_delivery_parts import notice_parts
from tests.ops import test_guardian_delivery as base

no_network = base.no_network
delivery_runtime = base.delivery_runtime
BODY = "\n".join(f"成交-{i:04d}：核对实际股数、成交金额和费用。" for i in range(180)) + "\n最后一笔成交-必须可见"


def queue(ledger, ops):
    channels = base.configure(ops)
    ops.set_setting("notify_channels", channels[:1])
    assert ledger.claim(base.SLOT)
    ledger.finish(base.SLOT, {"status": "success"}, notice={"title": "自主交易员 · 模拟账户", "body": BODY})


def test_every_content_line_survives_utf8_splitting():
    parts = notice_parts("自主交易员 · 模拟账户", BODY)
    assert len(parts) > 1
    assert all(len(f"【{title}】\n{body}".encode("utf-8")) <= 2048 for title, body in parts)
    text = "\n".join(body for _, body in parts)
    assert "最后一笔成交-必须可见" in text and "后续已截断" not in text
    for i in range(180):
        assert f"成交-{i:04d}" in text


def test_long_notice_resumes_only_unsent_parts(tmp_path, delivery_runtime):
    path = tmp_path / "outbox.db"
    send = Mock(side_effect=[{"success": True, "sent": ["wecom"]},
                             {"success": False, "sent": [], "errors": ["temporary failure"]}])
    with OpsStore(tmp_path / "ops.db") as ops:
        with GuardianStore(path) as ledger:
            queue(ledger, ops)
            first = deliver_pending(ledger, ops, send)[base.SLOT]
            assert not first["success"] and first["partial"]
            first_title = send.call_args_list[0].kwargs["title"]
            assert send.call_count == 2
        send.side_effect = None
        send.return_value = {"success": True, "sent": ["wecom"]}
        with GuardianStore(path) as ledger:
            last = deliver_pending(ledger, ops, send)[base.SLOT]
            assert last["success"] and ledger.notice_backlog()["total"] == 0
            assert sum(call.kwargs["title"] == first_title for call in send.call_args_list) == 1
            assert "最后一笔成交-必须可见" in send.call_args.kwargs["body"]
            row = ledger.conn.execute("SELECT receipt_json FROM guardian_notices").fetchone()
            saved = json.loads(row[0])
            target = next(iter(saved["channel_receipts"].values()))
            assert target["sent_parts"] == target["total_parts"] > 1
            assert deliver_pending(ledger, ops, send) == {}


def test_interruption_after_saved_part_does_not_resend_it(tmp_path, delivery_runtime):
    class Interrupted(BaseException):
        pass
    path = tmp_path / "interruption.db"
    send = Mock(side_effect=[{"success": True, "sent": ["wecom"]}, Interrupted()])
    clock, _, _ = delivery_runtime
    with OpsStore(tmp_path / "ops.db") as ops:
        with GuardianStore(path) as ledger:
            queue(ledger, ops)
            with pytest.raises(Interrupted):
                deliver_pending(ledger, ops, send)
            first_title = send.call_args_list[0].kwargs["title"]
        clock[0] += 301
        send.side_effect = None
        send.return_value = {"success": True, "sent": ["wecom"]}
        with GuardianStore(path) as ledger:
            assert deliver_pending(ledger, ops, send)[base.SLOT]["success"]
            assert sum(call.kwargs["title"] == first_title for call in send.call_args_list) == 1
