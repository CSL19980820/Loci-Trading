"""跨日竞价评价必须拿到原始轮次，不能沿用前一篇报告的因果判断。"""
from src.ops.application import guardian_review_data as review
from src.ops.application.guardian_review_prompts import review_system


def test_prior_auction_evidence_distinguishes_deferred_from_risk_only_failure(monkeypatch):
    monkeypatch.setattr(review, "scheduled_trading_days",
                        lambda start, end: ["2026-09-21", "2026-09-22"])

    class Ledger:
        def cycles_between(self, start, end):
            assert (start, end) == ("2026-09-21", "2026-09-22")
            return [
                {"slot": "2026-09-21T09:25:00+08:00", "status": "success",
                 "result": {"analysis_only": True, "decisions": [{"code": "600000"}],
                            "deferred": [{"code": "600000"}], "opening_plans": []}},
                {"slot": "2026-09-21T09:30:00+08:00", "status": "failed",
                 "result": {"risk_only": True, "decisions": [],
                            "rejects": [{"code": "600487", "reject_code": "liquidity_unconfirmed"}]}},
                {"slot": "2026-09-21T09:35:00+08:00", "status": "success", "result": {}},
            ]

    rows = review.prior_auction_evidence(Ledger(), "2026-09-23")
    assert len(rows) == 2
    assert rows[0]["deferred"] == 1 and rows[0]["opening_plans"] == 0
    assert rows[0]["analysis_only"] is True
    assert rows[1]["risk_only"] is True and rows[1]["decisions"] == 0
    assert rows[1]["rejects"] == [{"code": "600487", "reject_code": "liquidity_unconfirmed"}]
    assert rows[0]["archived_opening_plan_followup"] == {"available": False, "items": []}


def test_prior_auction_includes_only_archived_outcomes_matching_both_cycles(monkeypatch):
    monkeypatch.setattr(review, "scheduled_trading_days", lambda start, end: ["2026-09-22"])
    source = "2026-09-22T09:25:00+08:00"
    reviewed = "2026-09-22T09:30:00+08:00"
    plans = [{"id": f"{source}:{index}", "source_slot": source,
              "last_review_slot": reviewed, "order": {"code": code}, "status": status,
              "filled_quantity": quantity} for index, code, status, quantity in (
                  (0, "600000", "executed", 300), (1, "600001", "abandoned", 0))]

    class Ledger:
        def cycles_between(self, start, end):
            assert (start, end) == ("2026-09-22", "2026-09-22")
            return [
                {"slot": source, "status": "success", "result": {"analysis_only": True,
                    "opening_plans": [{"id": p["id"]} for p in plans]}},
                {"slot": reviewed, "status": "success", "result": {
                    "opening_plan_updates": [{"plan_id": p["id"], "status": p["status"]} for p in plans],
                    "fills": [{"code": "600000", "quantity": 300}]}},
            ]

        def report(self, period, day):
            assert (period, day) == ("daily", "2026-09-22")
            return {"status": "success", "result": {"facts": {"opening_plan_reconciliation": [
                *plans,
                {**plans[0], "source_slot": "2026-09-21T09:25:00+08:00"},
                {**plans[1], "last_review_slot": "2026-09-22T09:35:00+08:00"},
            ]}}}

    rows = review.prior_auction_evidence(Ledger(), "2026-09-23")
    followup = rows[0]["archived_opening_plan_followup"]
    assert followup["available"] is True and followup["unverified_count"] == 2
    assert [(p["status"], p["filled_quantity"], p["source_slot"], p["last_review_slot"])
            for p in followup["items"]] == [
                ("executed", 300, source, reviewed), ("abandoned", 0, source, reviewed)]
    assert "executed是成功执行，abandoned是模型主动放弃" in review_system(
        {}, "daily", {}, stage="retrospective")
