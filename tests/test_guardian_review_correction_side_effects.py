"""Correcting a report must not replay its watchlist decisions."""
from src.ledger import GuardianStore
from src.ops.application.guardian_review_digest import notification_digest


def test_report_correction_preserves_live_watchlist_and_does_not_renotify_actions(tmp_path):
    day = "2026-09-23"
    with GuardianStore(tmp_path / "palace.db") as store:
        first = store.claim_report("daily", day)
        store.finish_report("daily", day, first, {
            "status": "success", "revision": 1,
            "created_at": "2026-09-23T16:10:31+08:00",
            "facts": {"stock_names": {"600000": "原观察"}},
            "analysis": {"watchlist_updates": [
                {"code": "600000", "action": "watch", "reason": "原版观察"},
            ]},
        })
        before = store.state()["watchlist"]
        store.reopen_report("daily", day, "修正历史归因")
        second = store.claim_report("daily", day)
        store.finish_report("daily", day, second, {
            "status": "success", "revision": 2,
            "created_at": "2026-09-23T18:00:00+08:00",
            "facts": {"stock_names": {"600000": "原观察", "600001": "新观察"},
                      "correction_reason": "修正历史归因"},
            "analysis": {"watchlist_updates": [
                {"code": "600000", "action": "unwatch", "reason": "修正文案"},
                {"code": "600001", "action": "watch", "reason": "修正文案"},
            ]},
        })
        assert store.state()["watchlist"] == before
        assert store.report("daily", day)["result"]["revision"] == 2

    body = notification_digest({
        "period": "daily", "period_pnl_cents": 0, "trades": [],
        "account": {"equity_cents": 10000, "cash_cents": 10000, "positions": []},
        "watchlist": before,
    }, {"watchlist_updates": [{"code": "600000", "action": "unwatch", "reason": "修正"}]},
        share_url="https://example.test/shared/reports/new",
        observed_at="2026-09-23T18:00:00+08:00", revision=2)
    assert "观察调整" not in body
    assert "https://example.test/shared/reports/new" in body


def test_forged_second_revision_cannot_skip_watchlist_action(tmp_path):
    with GuardianStore(tmp_path / "palace.db") as store:
        token = store.claim_report("daily", "2026-09-23")
        try:
            store.finish_report("daily", "2026-09-23", token, {
                "status": "success", "revision": 2,
                "facts": {"correction_reason": "伪造更正"},
                "analysis": {"watchlist_updates": [
                    {"code": "600000", "action": "watch", "reason": "伪造"},
                ]},
            })
        except ValueError as error:
            assert "缺少已归档前版" in str(error)
        else:
            raise AssertionError("伪造 revision=2 应被拒绝")
        assert store.report("daily", "2026-09-23")["status"] == "running"
        assert store.state().get("watchlist", []) == []
