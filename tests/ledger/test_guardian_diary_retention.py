import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.ledger import GuardianDiaryStore

NOW = datetime(2026, 9, 16, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_compaction_preserves_idempotency_financial_state_and_recent_memory(tmp_path):
    with GuardianDiaryStore(tmp_path / "palace.db") as store:
        original = store.ledger.state()
        for index in range(60):
            at = NOW-timedelta(days=60-index)
            store.conn.execute("INSERT INTO guardian_cycles VALUES(?,?,?,?)", (
                at.date().isoformat()+":10:00", at.timestamp(), "success",
                json.dumps({"analysis": "实际工作摘要", "as_of": at.isoformat(),
                            "decision_context": "x"*10000, "fills": [], "decisions": []})))
        store.conn.commit()
        store.save_preferences({"days": 1, "max_entries": 20, "cleanup_hours": 1})
        assert store.compact(now=NOW, force=True, dry_run=True)["eligible"] == 20
        assert store.stats()["compacted_entries"] == 0
        result = store.compact(now=NOW, force=True)
        assert result["removed"] == 20
        assert store.stats()["total_runs"] == 60
        assert store.stats()["full_entries"] == 40
        assert store.ledger.state() == original
        assert all("decision_context" in row["result"] for row in store.ledger.recent(40))
        first = store.conn.execute("SELECT slot,result_json FROM guardian_cycles ORDER BY started LIMIT 1").fetchone()
        assert json.loads(first[1])["diary_compacted"] is True
        assert "decision_context" not in json.loads(first[1])
        assert not store.ledger.claim(first[0])


def test_list_card_projects_only_small_real_summary(tmp_path):
    with GuardianDiaryStore(tmp_path / "palace.db") as store:
        result = {"analysis": "最近真实工作", "as_of": NOW.isoformat(), "decision_context": "x"*500000,
                  "fills": [{"name": "测试股票", "code": "600001", "action": "buy", "side": "buy", "quantity": 100}]*20}
        store.conn.execute("INSERT INTO guardian_cycles VALUES(?,?,?,?)", (
            "2026-09-16:10:00", NOW.timestamp(), "success", json.dumps(result)))
        store.conn.commit()
        card = store.latest()[0]
        assert card["started"] == NOW.timestamp()
        assert card["result"]["analysis"] == "最近真实工作"
        assert len(card["result"]["fills"]) == 3
        assert len(json.dumps(card)) < 2000


def test_disabling_both_retention_conditions_does_not_clean(tmp_path):
    with GuardianDiaryStore(tmp_path / "palace.db") as store:
        store.save_preferences({"days": 0, "max_entries": 0, "cleanup_hours": 1})
        assert store.compact(now=NOW, force=True)["disabled"] is True
