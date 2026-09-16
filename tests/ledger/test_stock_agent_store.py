from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.ledger import StockAgentConflict, StockAgentStore, check_guardian_account
from src.ops.domain.stock_agent import StockAgentConfig

NOW = datetime(2026, 9, 16, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def config(name="龙头选手", **changes):
    return StockAgentConfig(name=name, kind="leader", provider="test", model="test",
                            enabled=True, **changes).model_dump()


def test_independent_accounts_and_tenants(tmp_path):
    with StockAgentStore(tmp_path / "one.db") as one, StockAgentStore(tmp_path / "two.db") as two:
        first = one.create(config(initial_capital_cents=1_000_000), now=NOW)
        second = one.create(config(name="接力二号", initial_capital_cents=2_000_000), now=NOW)
        assert first["state"]["cash_cents"] == 1_000_000
        assert second["state"]["cash_cents"] == 2_000_000
        assert two.list_profiles() == []
        with pytest.raises(KeyError):
            two.get(first["id"])


def test_funding_is_idempotent_and_is_not_profit(tmp_path):
    with StockAgentStore(tmp_path / "palace.db") as store:
        agent = store.create(config(initial_capital_cents=1_000_000), now=NOW)
        for _ in range(2):
            result = store.deposit(agent["id"], 200_000, "fund-request-1", now=NOW)
        assert result["config"]["initial_capital_cents"] == 1_000_000
        assert result["state"]["initial_capital_cents"] == 1_200_000
        assert result["state"]["cash_cents"] == 1_200_000
        assert result["state"]["total_pnl_cents"] == 0
        assert store.equity(agent["id"])["items"][0]["pnl_cents"] == 0
        assert store.history(agent["id"], kind="funding")["total"] == 2
        check_guardian_account(result["state"])
        with pytest.raises(StockAgentConflict):
            store.deposit(agent["id"], 300_000, "fund-request-1", now=NOW)


@pytest.mark.parametrize("mutation", ["fund", "pause", "rename"])
def test_stale_worker_cannot_overwrite_account_or_config(tmp_path, mutation):
    with StockAgentStore(tmp_path / "palace.db") as store:
        agent = store.create(config(), now=NOW)
        claimed = store.claim_run(agent["id"], "2026-09-16:intraday:10:00", "intraday", now=NOW)
        assert claimed
        if mutation == "fund":
            store.deposit(agent["id"], 10000, "fund-request-1", now=NOW)
        else:
            changed = {**agent["config"], **({"enabled": False} if mutation == "pause" else {"name": "新名字"})}
            store.update_config(agent["id"], changed, revision=agent["revision"])
        with pytest.raises(StockAgentConflict):
            store.finish_run(agent["id"], claimed["run_id"], claimed["state"], {"summary": "旧结果"}, now=NOW)
        assert store.history(agent["id"], kind="trades")["total"] == 0
        if mutation == "fund":
            assert store.get(agent["id"])["state"]["cash_cents"] == 20_010_000


def test_slot_once_and_expired_owner_cannot_commit(tmp_path):
    path = tmp_path / "palace.db"
    with StockAgentStore(path) as store, StockAgentStore(path) as other:
        agent = store.create(config(), now=NOW)
        first = store.claim_run(agent["id"], "2026-09-16:intraday:10:00", "intraday", now=NOW)
        assert first
        assert other.claim_run(agent["id"], "2026-09-16:manual:1", "intraday", now=NOW) is None
        later = NOW + timedelta(minutes=6)
        second = other.claim_run(agent["id"], "2026-09-16:intraday:10:05", "intraday", now=later)
        assert second
        with pytest.raises(StockAgentConflict):
            store.finish_run(agent["id"], first["run_id"], first["state"], {}, now=later)
        other.finish_run(agent["id"], second["run_id"], second["state"], {"summary": "观察"}, now=later)
        assert store.claim_run(agent["id"], "2026-09-16:intraday:10:05", "intraday", now=later) is None
        assert store.get(agent["id"])["total_runs"] == 2


def test_commit_failure_rolls_back_all_financial_writes(tmp_path):
    with StockAgentStore(tmp_path / "palace.db") as store:
        agent = store.create(config(), now=NOW)
        claimed = store.claim_run(agent["id"], "2026-09-16:intraday:10:00", "intraday", now=NOW)
        def stale_quote():
            raise ValueError("报价已过期")
        with pytest.raises(ValueError, match="报价已过期"):
            store.finish_run(agent["id"], claimed["run_id"], claimed["state"], {"fills": [{"code": "600000"}]},
                             now=NOW, before_commit=stale_quote)
        assert store.history(agent["id"], kind="trades")["total"] == 0
        assert store.get(agent["id"])["state"] == agent["state"]


def test_cleanup_keeps_counts_context_and_all_financial_history(tmp_path):
    with StockAgentStore(tmp_path / "palace.db") as store:
        agent = store.create(config(retention={"days": 1, "max_entries": 20, "cleanup_hours": 1}), now=NOW)
        for day in range(30):
            at = NOW + timedelta(days=day)
            claimed = store.claim_run(agent["id"], at.date().isoformat() + ":review:20:00", "review", now=at)
            store.finish_run(agent["id"], claimed["run_id"], claimed["state"], {"summary": "复盘正文"}, now=at)
        result = store.prune_diary(agent["id"], now=NOW + timedelta(days=31), force=True)
        assert result["removed"] == 10
        latest = store.get(agent["id"])
        assert latest["total_runs"] == 30
        assert latest["history_kept"] == 20
        assert latest["cleaned_runs"] == 10
        assert store.history(agent["id"], kind="funding")["total"] == 1
        assert store.equity(agent["id"])["total"] == 30
        assert len(store.history(agent["id"], limit=3)["items"]) == 3
        assert "detail" not in store.history(agent["id"])["items"][0]
        with pytest.raises(ValueError, match="当天"):
            store.claim_run(agent["id"], "2026-09-16:review:20:00", "review", now=NOW + timedelta(days=31))


@pytest.mark.parametrize("field,value", [("position_limit", 4), ("temporary_position_limit", 6),
                                         ("watch_limit", 4), ("daily_selection_limit", 4)])
def test_leader_configuration_cannot_raise_user_hard_limits(field, value):
    with pytest.raises(ValueError):
        config(**{field: value})
