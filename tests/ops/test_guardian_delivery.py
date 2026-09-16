"""Guardian outbox retries use persisted channel receipts, not aggregate success."""
from __future__ import annotations

import json
import smtplib
import urllib.request
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ledger import GuardianStore
from src.ledger.infrastructure import guardian_notices
from src.ops.application import notify_dispatch, notify_registry
from src.ops.application.guardian_delivery import deliver_pending
from src.ops.application.notify import NotifyError
from src.ops.application.notify_bark import BarkError
from src.ops.infrastructure.store import OpsStore

SLOT = "2026-09-15T10:00"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    leaked = []

    def blocked(*args, **kwargs):
        leaked.append("network")
        raise AssertionError("external notification must be mocked")

    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(smtplib, "SMTP", blocked)
    monkeypatch.setattr(smtplib, "SMTP_SSL", blocked)
    yield
    assert not leaked


@pytest.fixture
def delivery_runtime(monkeypatch):
    clock = [1000.0]
    timer = SimpleNamespace(time=lambda: clock[0])
    for module in (notify_dispatch, notify_registry, guardian_notices):
        monkeypatch.setattr(module, "time", timer)
    wecom = Mock(side_effect=NotifyError("wecom failed"))
    bark = Mock()
    monkeypatch.setattr(notify_dispatch, "send_wecom_text", wecom)
    monkeypatch.setattr(notify_dispatch, "send_bark_text", bark)
    return clock, wecom, bark


def configure(ops):
    channels = [
        {"id": "company-primary", "type": "wecom", "enabled": True,
         "is_default": True, "config": {"url": "https://example.invalid/company"}},
        {"id": "phone-main", "type": "bark", "enabled": True,
         "is_default": True, "config": {"device_key": "guardian-test-device"}},
    ]
    ops.set_setting("notify_channels", channels)
    return channels


def queue(ledger, slot=SLOT):
    assert ledger.claim(slot)
    ledger.finish(slot, {"status": "success"},
                  notice={"title": "Guardian", "body": "saved execution"})


def saved(ledger, slot=SLOT):
    row = ledger.conn.execute("SELECT * FROM guardian_notices WHERE slot=?", (slot,)).fetchone()
    return dict(row), json.loads(row["receipt_json"])


def test_partial_retry_does_not_repeat_successful_bark(tmp_path, delivery_runtime):
    clock, wecom, bark = delivery_runtime
    path = tmp_path / "ledger.db"
    with OpsStore(tmp_path / "ops.db") as ops:
        configure(ops)
        with GuardianStore(path) as ledger:
            queue(ledger)
            first = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]
        clock[0] += 61
        with GuardianStore(path) as ledger:
            second = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]
            assert first["partial"] and second["partial"]
            assert wecom.call_count == 2
            assert bark.call_count == 1
            assert saved(ledger)[0]["status"] == "pending"
            clock[0] += 61
            wecom.side_effect = None
            final = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]
            assert final["success"] and not final["partial"]
            assert final["sent"] == ["bark", "wecom"]
            assert wecom.call_count == 3 and bark.call_count == 1
            assert saved(ledger)[0]["status"] == "sent"
            assert ledger.recent()[0]["result"]["notify"] == final
            assert deliver_pending(ledger, ops, notify_dispatch.dispatch_text) == {}


def test_configuration_changes_do_not_expand_or_repeat_original_targets(delivery_runtime) -> None:
    clock, wecom, bark = delivery_runtime
    with OpsStore(None) as ops, GuardianStore() as ledger:
        channels = configure(ops)
        queue(ledger)
        deliver_pending(ledger, ops, notify_dispatch.dispatch_text)
        channels[1]["config"]["device_key"] = "changed-successful-device"
        added = {**channels[1], "id": "new-phone"}
        ops.set_setting("notify_channels", [channels[1], added])
        clock[0] += 61
        receipt = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]
        assert receipt["skipped"] == "channel_unavailable"
        assert not receipt["success"] and wecom.call_count == bark.call_count == 1
        channels[0].update(enabled=False, is_default=False)
        channels[0]["config"]["url"] = "https://example.invalid/repaired"
        ops.set_setting("notify_channels", channels + [added])
        assert not deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]["success"]
        assert wecom.call_count == bark.call_count == 1
        channels[0]["enabled"] = True
        ops.set_setting("notify_channels", channels + [added])
        wecom.side_effect = None
        receipt = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]
        assert receipt["success"] and len(receipt["channel_targets"]) == 2
        assert wecom.call_args.args[0] == "https://example.invalid/repaired"
        assert wecom.call_count == 2 and bark.call_count == 1
        serialized = json.dumps(saved(ledger)[1])
        assert "guardian-test-device" not in serialized
        assert "https://example.invalid" not in serialized
        assert "changed-successful-device" not in serialized


@pytest.mark.parametrize("target_state", ["removed", "disabled"])
def test_unavailable_old_targets_do_not_starve_new_notices(target_state, delivery_runtime) -> None:
    clock, wecom, bark = delivery_runtime
    old_slots = ["notice-01", "notice-02", "notice-03"]
    fresh_slot = "notice-04"
    with OpsStore(None) as ops, GuardianStore() as ledger:
        old_target = configure(ops)[0]
        ops.set_setting("notify_channels", [old_target])
        for slot in old_slots:
            assert ledger.claim(slot)
            ledger.finish(slot, {"status": "success"}, notice={"title": slot, "body": slot})
        first = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)
        assert list(first) == old_slots and not any(row["success"] for row in first.values())
        assert wecom.call_count == 3
        new_target = {**old_target, "id": "company-new",
                      "config": {"url": "https://example.invalid/new"}}
        targets = [new_target]
        if target_state == "disabled":
            targets.append({**old_target, "enabled": False})
        ops.set_setting("notify_channels", targets)
        clock[0] += 61
        wecom.side_effect = None
        assert ledger.claim(fresh_slot)
        ledger.finish(fresh_slot, {"status": "success"},
                      notice={"title": fresh_slot, "body": fresh_slot})
        second = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)
        assert fresh_slot in second, "Permanent failures must not monopolize the three-notice batch"
        assert second[fresh_slot]["success"] and saved(ledger, fresh_slot)[0]["status"] == "sent"
        assert wecom.call_count == 4 and not bark.called
        assert wecom.call_args.args[0] == "https://example.invalid/new"
        assert all(saved(ledger, slot)[0]["status"] == "pending" for slot in old_slots)


def test_claim_rotation_survives_reopening_the_outbox(tmp_path, delivery_runtime) -> None:
    path = tmp_path / "fair-outbox.db"
    slots = ["notice-01", "notice-02", "notice-03", "notice-04", "notice-05"]
    with GuardianStore(path) as ledger:
        for slot in slots:
            queue(ledger, slot)
        first = ledger.claim_notices()
        assert [row["slot"] for row in first] == slots[:3]
        for row in first:
            assert ledger.finish_notice(row["slot"], row["attempts"], {"success": False})
    with GuardianStore(path) as ledger:
        second = ledger.claim_notices()
        assert [row["slot"] for row in second] == [slots[3], slots[4], slots[0]]
        assert [row["attempts"] for row in second] == [1, 1, 2]
        for row in second:
            assert ledger.finish_notice(row["slot"], row["attempts"], {"success": False})
        third = ledger.claim_notices()
        assert [row["slot"] for row in third] == [slots[1], slots[2], slots[3]]


def test_two_bark_ids_are_checkpointed_independently(delivery_runtime) -> None:
    clock, wecom, bark = delivery_runtime
    with OpsStore(None) as ops, GuardianStore() as ledger:
        phone = configure(ops)[1]
        other = {**phone, "id": "phone-two", "config": {"device_key": "second-device"}}
        ops.set_setting("notify_channels", [phone, other])
        queue(ledger)
        first = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]
        assert first["partial"] and not first["success"]
        assert len(first["channel_targets"]) == 2
        assert bark.call_count == 1 and not wecom.called
        clock[0] += 61
        assert deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]["success"]
        assert [call.kwargs["device_key"] for call in bark.call_args_list] == [
            "guardian-test-device", "second-device"]


def test_expired_and_replaced_leases_cannot_save_receipts(tmp_path, delivery_runtime) -> None:
    clock, _, _ = delivery_runtime
    path = tmp_path / "leases.db"
    with GuardianStore(path) as first, GuardianStore(path) as second:
        queue(first)
        old = first.claim_notices()[0]
        assert second.claim_notices() == []
        assert first.record_notice_progress(SLOT, old["attempts"], {"marker": "old"})
        clock[0] += 300
        assert not first.record_notice_progress(SLOT, old["attempts"], {"marker": "expired"})
        assert not first.finish_notice(SLOT, old["attempts"], {"success": True})
        new = second.claim_notices()[0]
        assert new["attempts"] == old["attempts"] + 1
        assert second.record_notice_progress(SLOT, new["attempts"], {"marker": "new"})
        assert not first.record_notice_progress(SLOT, old["attempts"], {"marker": "stale"})
        assert not first.finish_notice(SLOT, old["attempts"], {"success": True})
        assert saved(second)[1] == {"marker": "new"}
        final = {"success": True, "sent": ["wecom"]}
        assert second.finish_notice(SLOT, new["attempts"], final)
        assert saved(first)[0]["status"] == "sent"
        assert first.recent()[0]["result"]["notify"] == final


def test_same_notice_is_isolated_between_tenants(delivery_runtime) -> None:
    from src.shared.tenancy import tenant_scope

    clock, wecom, bark = delivery_runtime
    for tenant in ("delivery-a", "delivery-b"):
        with tenant_scope(tenant), OpsStore(None) as ops, GuardianStore() as ledger:
            configure(ops)
            queue(ledger)
            assert deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]["partial"]
    assert bark.call_count == wecom.call_count == 2
    clock[0] += 61
    wecom.side_effect = None
    with tenant_scope("delivery-a"), OpsStore(None) as ops, GuardianStore() as ledger:
        assert deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]["success"]
    with tenant_scope("delivery-b"), OpsStore(None) as ops, GuardianStore() as ledger:
        assert saved(ledger)[0]["status"] == "pending"
        assert not saved(ledger)[1]["success"]
        assert deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]["success"]
    assert bark.call_count == 2 and wecom.call_count == 4


@pytest.mark.parametrize("registry_success", [True, False])
def test_registry_channels_keep_their_own_receipts(registry_success, monkeypatch, delivery_runtime) -> None:
    clock, wecom, bark = delivery_runtime
    feishu = SimpleNamespace(name="feishu", label="Feishu",
                             is_configured=lambda cfg: bool(cfg.get("url")),
                             send=Mock(return_value=registry_success))
    real_get = notify_registry.get_channel
    monkeypatch.setattr(notify_registry, "get_channel",
                        lambda name: feishu if name == "feishu" else real_get(name))
    with OpsStore(None) as ops, GuardianStore() as ledger:
        configure(ops)
        ops.set_setting("notify:feishu", {"url": "https://example.invalid/feishu"})
        queue(ledger)
        first = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]
        assert first["partial"] and len(first["channel_targets"]) == 3
        assert feishu.send.call_count == bark.call_count == wecom.call_count == 1
        clock[0] += 61
        wecom.side_effect = None
        feishu.send.return_value = True
        receipt = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]
        assert receipt["success"] and receipt["sent"] == ["bark", "feishu", "wecom"]
        assert bark.call_count == 1 and wecom.call_count == 2
        assert feishu.send.call_count == (1 if registry_success else 2)


def test_crash_after_checkpoint_retries_only_unsent_channel(tmp_path, delivery_runtime) -> None:
    clock, wecom, bark = delivery_runtime

    class Interrupted(BaseException):
        pass

    def interrupted(store, **kwargs) -> dict:
        if kwargs.get("channel_ids") == ["company-primary"]:
            raise Interrupted()
        return notify_dispatch.dispatch_text(store, **kwargs)

    path = tmp_path / "crash.db"
    with OpsStore(None) as ops:
        channels = configure(ops)
        ops.set_setting("notify_channels", channels[::-1])
        with GuardianStore(path) as ledger:
            queue(ledger)
            with pytest.raises(Interrupted):
                deliver_pending(ledger, ops, interrupted)
            row, receipt = saved(ledger)
            assert row["status"] == "sending" and receipt["sent"] == ["bark"]
            assert bark.call_count == 1 and not wecom.called
        clock[0] += 300
        wecom.side_effect = None
        with GuardianStore(path) as ledger:
            receipt = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]
            assert receipt["success"] and receipt["delivery_attempt"] == 2
            assert bark.call_count == wecom.call_count == 1


def test_old_aggregate_partial_receipt_preserves_known_success(delivery_runtime) -> None:
    _, wecom, bark = delivery_runtime
    wecom.side_effect = None
    with OpsStore(None) as ops, GuardianStore() as ledger:
        configure(ops)
        queue(ledger)
        claim = ledger.claim_notices()[0]
        assert ledger.finish_notice(SLOT, claim["attempts"],
                                    {"success": False, "partial": True, "sent": ["bark"]})
        assert deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]["success"]
        assert wecom.call_count == 1 and not bark.called


def test_losing_lease_during_send_stops_following_channels(tmp_path, delivery_runtime) -> None:
    clock, wecom, bark = delivery_runtime
    path = tmp_path / "handover.db"
    with OpsStore(None) as ops, GuardianStore(path) as ledger, GuardianStore(path) as replacement:
        channels = configure(ops)
        ops.set_setting("notify_channels", channels[::-1])
        queue(ledger)

        def replaced(store, **kwargs) -> dict:
            receipt = notify_dispatch.dispatch_text(store, **kwargs)
            clock[0] += 301
            claim = replacement.claim_notices()[0]
            assert replacement.record_notice_progress(SLOT, claim["attempts"], {"marker": "replacement"})
            return receipt

        receipt = deliver_pending(ledger, ops, replaced)[SLOT]
        assert receipt["skipped"] == "lease_lost" and not receipt["success"]
        assert bark.call_count == 1 and not wecom.called
        assert saved(ledger)[1] == {"marker": "replacement"}


def test_outbox_and_cycle_completion_still_commit_atomically(delivery_runtime) -> None:
    import sqlite3

    with GuardianStore() as ledger:
        assert ledger.claim(SLOT)
        checked = []

        def fail_after_queue() -> None:
            checked.append(True)
            if len(checked) == 2:
                raise RuntimeError("abort commit")

        with pytest.raises(RuntimeError, match="abort commit"):
            ledger.finish(SLOT, {"status": "success"}, before_commit=fail_after_queue,
                          notice={"title": "Guardian", "body": "not committed"})
        assert ledger.conn.execute("SELECT count(*) FROM guardian_notices").fetchone()[0] == 0
        ledger.finish(SLOT, {"status": "success"}, notice={"title": "Guardian", "body": "committed"})
        claim = ledger.claim_notices()[0]
        ledger.conn.execute("CREATE TEMP TRIGGER reject_notify BEFORE UPDATE ON guardian_cycles "
                            "BEGIN SELECT RAISE(ABORT, 'reject notify'); END")
        with pytest.raises(sqlite3.IntegrityError, match="reject notify"):
            ledger.finish_notice(SLOT, claim["attempts"], {"success": True})
        row, receipt = saved(ledger)
        assert row["status"] == "sending" and receipt == {}
        assert "notify" not in ledger.recent()[0]["result"]


def test_all_failed_channels_remain_retryable(delivery_runtime) -> None:
    clock, wecom, bark = delivery_runtime
    bark.side_effect = BarkError("bark failed")
    with OpsStore(None) as ops, GuardianStore() as ledger:
        configure(ops)
        queue(ledger)
        for _ in range(2):
            receipt = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]
            assert not receipt["success"] and not receipt["partial"]
            assert receipt["sent"] == [] and len(receipt["errors"]) == 2
            assert saved(ledger)[0]["status"] == "pending"
            clock[0] += 61
        assert wecom.call_count == bark.call_count == 2
        wecom.side_effect = bark.side_effect = None
        assert deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]["success"]
        assert wecom.call_count == bark.call_count == 3


def test_rate_limited_failure_is_not_mistaken_for_delivery(delivery_runtime) -> None:
    clock, wecom, bark = delivery_runtime
    with OpsStore(None) as ops, GuardianStore() as ledger:
        configure(ops)
        queue(ledger)
        deliver_pending(ledger, ops, notify_dispatch.dispatch_text)
        receipt = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]
        assert receipt["skipped"] == "rate_limited"
        assert receipt["partial"] and not receipt["success"]
        assert receipt["sent"] == ["bark"]
        assert wecom.call_count == bark.call_count == 1
        assert saved(ledger)[0]["status"] == "pending"
        clock[0] += 61
        wecom.side_effect = None
        assert deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]["success"]
        assert wecom.call_count == 2 and bark.call_count == 1


@pytest.mark.parametrize("reason", ["quiet_hours", "market_closed"])
def test_silence_keeps_unsent_targets_pending(reason, monkeypatch, delivery_runtime) -> None:
    _, wecom, bark = delivery_runtime
    wecom.side_effect = None
    with OpsStore(None) as ops, GuardianStore() as ledger:
        configure(ops)
        queue(ledger)
        if reason == "quiet_hours":
            ops.set_setting("notify_policy", {"quiet_hours": "00:00-00:00"})
        else:
            monkeypatch.setattr("src.ops.application.notify_calendar.notification_silence_reason", lambda: reason)
        receipt = deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]
        assert receipt["skipped"] == reason and receipt["sent"] == []
        assert not receipt["success"] and not wecom.called and not bark.called
        assert saved(ledger)[0]["status"] == "pending"
        ops.set_setting("notify_policy", {})
        monkeypatch.setattr("src.ops.application.notify_calendar.notification_silence_reason", lambda: "")
        assert deliver_pending(ledger, ops, notify_dispatch.dispatch_text)[SLOT]["success"]
        assert wecom.call_count == bark.call_count == 1
