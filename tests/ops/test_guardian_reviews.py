from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.ledger import GuardianStore
from src.market import scheduled_trading_days
from src.ops.application.guardian_config import save_config
from src.ops.application.guardian_decision import GuardianDecision, simulate
from src.ops.application.guardian_review_data import build_review_facts, report_window
from src.ops.application.jobs import guardian_review
from src.ops.application.jobs.context import JobContext, JobError
from src.ops.infrastructure.store import OpsStore

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 14, 16, tzinfo=TZ)


class Market:
    days = ["2026-09-11", "2026-09-14", "2026-09-15", "2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"]
    prices = {"2026-09-14": 9.5, "2026-09-15": 11.5, "2026-09-18": 10,
              "2026-09-21": 10.5, "2026-09-22": 10.3, "2026-09-23": 11, "2026-09-24": 10.8}
    source = "tdx"
    fetched_time = "07:10:00"

    def trading_days(self, start=None, end=None):
        return [d for d in self.days if (start is None or d >= start) and (end is None or d <= end)]

    def history(self, code, *, start, end, adjust):
        assert adjust == "none" and start == end
        return pd.DataFrame([{"trade_date": end, "close": self.prices.get(end, 10),
                              "source": self.source, "fetched_at": f"{end} {self.fetched_time}"}])


def seed(ledger, *, action="buy", quantity=1000, day=14, price=10):
    now = NOW.replace(day=day, hour=10)
    decision = GuardianDecision.model_validate({"summary": "fixture", "orders": [
        {"code": "603920", "action": action, "quantity": quantity, "reason": "测试"}]})
    state, fills, rejects = simulate(ledger.state(), decision, [], {"603920": {"price": price,
        "name": "测试持仓", "trade_date": now.date().isoformat(), "trade_time": "10:00:00"}}, now)
    assert not rejects
    slot = now.isoformat()
    assert ledger.claim(slot)
    ledger.finish(slot, {"status": "success", "fills": fills}, state)


def test_daily_replays_trades_and_uses_exact_close_not_later_account(tmp_path):
    with GuardianStore(tmp_path / "ledger.db") as ledger:
        seed(ledger)
        seed(ledger, action="sell", quantity=500, day=15, price=11)
        today = build_review_facts(ledger, Market(), "daily", "2026-09-14", NOW.replace(day=15))
        assert today["account"]["positions"][0]["quantity"] == 1000
        assert today["period_pnl_cents"] == -50260
        assert today["period_fees_cents"] == 260
        assert today["stock_performance"][0]["period_pnl_cents"] == -50260
        assert not ledger.apply_close_valuation(today["account"], "2026-09-14")
        assert ledger.state()["positions"][0]["quantity"] == 500
        tomorrow = build_review_facts(ledger, Market(), "daily", "2026-09-15", NOW.replace(day=15))
        assert tomorrow["period_pnl_cents"] == 174581
        assert tomorrow["period_realized_pnl_cents"] == 49451
        assert tomorrow["period_fees_cents"] == 419


def test_review_distinguishes_expired_cycles_and_missing_stock_assessments(tmp_path):
    with GuardianStore(tmp_path / "ledger.db") as ledger:
        slot = "2026-09-14T09:30:00+08:00"
        assert ledger.claim(slot)
        ledger.finish(slot, {"status": "expired", "error": "进程中断",
            "candidates": [{"code": "300537"}], "decisions": []})
        facts = build_review_facts(ledger, Market(), "daily", "2026-09-14", NOW)
        assert facts["execution_facts"]["failed_cycles"] == 0
        assert facts["execution_facts"]["expired_cycles"] == 1
        assert facts["execution_facts"]["expired_cycle_slots"] == [slot]
        assert facts["cycles"][0]["candidate_assessments"] == [{"code": "300537", "status": "not_recorded"}]
        assert facts["cycles"][0]["policy_evidence"] == "not_recorded"


def test_premarket_uses_yesterday_close_and_today_sellable_shares(tmp_path):
    with GuardianStore(tmp_path / "ledger.db") as ledger:
        seed(ledger)
        facts = build_review_facts(ledger, Market(), "premarket", "2026-09-15", NOW.replace(day=15, hour=8, minute=50))
        assert facts["baseline_date"] == "2026-09-14"
        assert facts["account"]["positions"][0]["available_quantity"] == 1000
        assert facts["account"]["positions"][0]["mark_price_cents"] == 950
        assert facts["trades"] == []
        assert facts["account"]["valuation_kind"] == "previous_close"


def test_week_ends_on_last_exchange_day_including_holidays(tmp_path):
    assert scheduled_trading_days("2026-09-21", "2026-09-27")[-1] == "2026-09-24"
    assert report_window("weekly", "2026-09-30", NOW.replace(day=30)) == ("2026-09-28", "2026-09-30")
    with pytest.raises(LookupError):
        report_window("weekly", "2026-09-23", NOW.replace(day=23))
    with pytest.raises(ValueError):
        scheduled_trading_days("2027-01-01", "2027-01-07")
    with GuardianStore(tmp_path / "ledger.db") as ledger:
        seed(ledger)
        facts = build_review_facts(ledger, Market(), "weekly", "2026-09-24", NOW.replace(day=24))
        assert facts["period_pnl_cents"] == 80000
        assert len(facts["equity_points"]) == 5
        assert facts["next_trade_date"] == "2026-09-28"
        assert facts["close_drawdown_pct"] < 0


@pytest.mark.parametrize("source,fetched", [("tdx_spot", "07:10:00"), ("tdx", "06:59:59")])
def test_intraday_or_non_authoritative_close_is_rejected(tmp_path, source, fetched):
    market = Market(); market.source = source; market.fetched_time = fetched
    with GuardianStore(tmp_path / "ledger.db") as ledger:
        seed(ledger)
        with pytest.raises(ValueError):
            build_review_facts(ledger, market, "daily", "2026-09-14", NOW)
    with pytest.raises(LookupError):
        report_window("daily", "2026-09-14", NOW.replace(hour=15, minute=30))


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(guardian_review, "datetime", SimpleNamespace(now=lambda tz: NOW))
    analysis = {"summary": "持仓回落，复盘入场条件。", "assessments": ["区分正常波动与决策错误"], "plans": [], "lessons": []}
    generate = Mock(return_value=(analysis, {"model": "test"}, []))
    notify = Mock(return_value={"success": True})
    monkeypatch.setattr(guardian_review, "generate_review", generate)
    monkeypatch.setattr(guardian_review, "dispatch_text", notify)
    with OpsStore(tmp_path / "ops.db") as ops:
        ops.set_setting('wecom_webhook', {'url': 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-review-only'})
        save_config(ops, {"enabled": True, "model": "test", "provider": "test", "notify": True})
        context = JobContext(ops_store=ops, palace_db=str(tmp_path / "ledger.db"))
        monkeypatch.setattr(context, "market", lambda: nullcontext(Market()))
        with GuardianStore(context.palace_db) as ledger:
            seed(ledger)
        yield context, generate, notify


def test_report_generated_once_close_revalued_and_costs_sent(runtime):
    context, generate, notify = runtime
    first = guardian_review.execute_guardian_review({"period": "daily"}, context)
    second = guardian_review.execute_guardian_review({"period": "daily"}, context)
    assert first["period_pnl_cents"] == -50260 and second["reused"]
    assert generate.call_count == notify.call_count == 1
    assert "成本 10.0026元/股" in notify.call_args.kwargs["body"]
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.trades()["total"] == 1
        assert ledger.state()["valuation_kind"] == "official_close"
        assert ledger.state()["cash_cents"] == 18999740
        assert ledger.state()["equity_cents"] == 19949740
        assert ledger.report("daily", "2026-09-14")["result"]["notify"]["success"]


def test_model_failure_can_retry_without_false_success(runtime):
    context, generate, notify = runtime
    good = generate.return_value
    generate.side_effect = RuntimeError("模型暂不可用")
    with pytest.raises(JobError):
        guardian_review.execute_guardian_review({"period": "daily"}, context)
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.report("daily", "2026-09-14")["status"] == "failed"
        assert ledger.trades()["total"] == 1
    assert notify.call_count == 1 and "尚未完成" in notify.call_args.kwargs["body"]
    generate.side_effect = None; generate.return_value = good
    assert guardian_review.execute_guardian_review({"period": "daily"}, context)["status"] == "success"


def test_failed_notification_retries_without_regenerating_report(runtime):
    context, generate, notify = runtime
    notify.side_effect = [{"success": False, "errors": ["network"]}, {"success": True}]
    with pytest.raises(JobError, match="通知未送达"):
        guardian_review.execute_guardian_review({"period": "daily"}, context)
    assert guardian_review.execute_guardian_review({"period": "daily"}, context)["reused"]
    assert generate.call_count == 1 and notify.call_count == 2


def test_full_report_chunks_resume_after_failure_with_no_truncation(runtime):
    import re
    context, generate, notify = runtime
    generate.return_value[0]['summary'] = '完整报告😀中文内容。' * 600
    notify.side_effect = [{'success': True, 'sent': ['wecom']}, {'success': False, 'errors': ['timeout']}]
    with pytest.raises(JobError, match='第2/'):
        guardian_review.execute_guardian_review({'period':'daily'}, context)
    first_body = notify.call_args_list[0].kwargs['body']
    with GuardianStore(context.palace_db) as ledger:
        partial = ledger.report('daily','2026-09-14')['result']['notify']
        assert partial['sent_parts'] == 1 and not partial['success']
        assert partial['total_parts'] > 6
    notify.side_effect = None
    notify.return_value = {'success': True, 'sent': ['wecom']}
    notify.reset_mock()
    assert guardian_review.execute_guardian_review({'period':'daily'}, context)['reused']
    assert generate.call_count == 1
    received = first_body + ''.join(c.kwargs['body'] for c in notify.call_args_list)
    with GuardianStore(context.palace_db) as ledger:
        result = ledger.report('daily','2026-09-14')['result']
        assert re.sub(r'\s','', received) == re.sub(r'\s','',result['body'])
        assert result['notify']['success'] and result['notify']['sent_parts'] == result['notify']['total_parts']
    for call in notify.call_args_list:
        assert len(('【'+call.kwargs['title']+'】\n'+call.kwargs['body']).encode('utf-8')) <= 2048
        assert '已截断' not in call.kwargs['body']


def test_close_confirmation_cannot_be_scheduled_at_1450():
    from src.ops.application.guardian_review_agent import normalize_plan_timing
    analysis={'plans':[{'action':'stop_loss','trigger':'收盘跌破14.40','timing':'14:50确认收盘价'}, {'action':'stop_loss','trigger':'盘中跌幅超过6%不等收盘','timing':'盘中轮次'}, {'action':'hold','trigger':'持有到收盘','timing':'持续观察'}]}
    normalized=normalize_plan_timing(analysis)
    assert '14:50' not in normalized['plans'][0]['timing']
    assert '计划日之后的下一交易日' in normalized['plans'][0]['timing']
    assert normalized['plans'][1]['timing']=='盘中轮次'
    assert normalized['plans'][2]['timing']=='持续观察'
    buy={'plans':[{'action':'buy','trigger':'次日开盘买入，持有两日后收盘退出','timing':'计划日开盘后研判'}]}
    assert normalize_plan_timing(buy)['plans'][0]['timing']=='计划日开盘后研判'


def test_correction_archives_original_and_preserves_revision_after_failure(runtime):
    import json
    context, generate, notify = runtime
    first = guardian_review.execute_guardian_review({"period": "daily"}, context)
    with GuardianStore(context.palace_db) as ledger:
        ledger.reopen_report("daily", "2026-09-14", "更正时点归因")
        original = ledger.conn.execute("SELECT revision,result_json FROM guardian_report_revisions").fetchone()
        assert original["revision"] == 1
        assert json.loads(original["result_json"])["body"] == first["body"]
        assert ledger.report("daily", "2026-09-14")["result"]["next_revision"] == 2
    generate.side_effect = RuntimeError("retry")
    with pytest.raises(JobError):
        guardian_review.execute_guardian_review({"period": "daily"}, context)
    generate.side_effect = None
    corrected = guardian_review.execute_guardian_review({"period": "daily"}, context)
    assert corrected["period_pnl_cents"] == first["period_pnl_cents"]
    assert "更正" in notify.call_args.kwargs["title"]
    facts = generate.call_args.args[2]
    assert facts["correction_reason"] == "更正时点归因"
    assert not facts["execution_facts"]["has_premarket_report"]
    assert facts["execution_facts"]["trade_records"] == 1
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.report("daily", "2026-09-14")["result"]["revision"] == 2
        assert ledger.trades()["total"] == 1
    count = notify.call_count
    guardian_review.execute_guardian_review({"period": "daily"}, context)
    assert notify.call_count == count


def test_two_workers_cannot_claim_same_report(tmp_path):
    path = tmp_path / "ledger.db"
    with GuardianStore(path):
        pass
    barrier = Barrier(2)
    def claim():
        with GuardianStore(path) as ledger:
            barrier.wait(timeout=5)
            return ledger.claim_report("daily", "2026-09-14")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sum(token is not None for token in results) == 1


def test_jobs_created_on_enable_and_respect_individual_switches(tmp_path):
    from src.ops.application.ensure_guardian_review_jobs import ensure_guardian_review_jobs, REVIEW_JOBS
    from src.ops.application.job_quota import is_managed_job
    with OpsStore(tmp_path / "ops.db") as store:
        save_config(store, {"enabled": False})
        assert all(store.get_job_by_name(name) is None for name, _ in REVIEW_JOBS.values())
        save_config(store, {"enabled": True})
        for name, cron in REVIEW_JOBS.values():
            job = store.get_job_by_name(name)
            assert job["enabled"] and job["cron"] == cron and is_managed_job(job)
        daily = store.get_job_by_name(REVIEW_JOBS["daily"][0])
        store.update_job(daily["id"], enabled=False, cron="0 16 * * mon-fri")
        ensure_guardian_review_jobs(store)
        assert not store.get_job(daily["id"])["enabled"]
        assert store.get_job(daily["id"])["cron"] == "0 16 * * mon-fri"


def test_reports_are_tenant_isolated():
    from src.shared.tenancy import tenant_scope
    with tenant_scope("review_one"), GuardianStore() as ledger:
        token = ledger.claim_report("daily", "2026-09-14")
        ledger.finish_report("daily", "2026-09-14", token, {"status": "success", "body": "private"})
    with tenant_scope("review_two"), GuardianStore() as ledger:
        assert ledger.reports() == []
        assert ledger.report("daily", "2026-09-14") is None


def test_unknown_evidence_is_rejected_and_write_tools_are_unavailable(monkeypatch):
    import json
    from src.ai import ProviderConfig
    from src.ops.application.guardian_review_agent import generate_review
    provider = ProviderConfig("test", "openai_compatible", "https://example.invalid", "test", "test")
    monkeypatch.setattr("src.ai.resolve_config", lambda *a, **kw: provider)
    monkeypatch.setattr("src.ai.record_llm_usage", lambda **kw: None)
    source_call = Mock(return_value={"text": "read-only data"})
    schemas = [{"type": "function", "function": {"name": name}} for name in ("wudao__cls_news", "wudao__watchlist_update")]
    monkeypatch.setattr("src.ops.application.guardian_review_agent.agent_tools", lambda *a, **kw: ([s for s in schemas if not s["function"]["name"].endswith("watchlist_update")], source_call, {}))
    def run(*a, **kw):
        if kw.get("tool_schemas"):
            names = {t["function"]["name"] for t in kw["tool_schemas"]}
            assert "wudao__cls_news" in names and "system__web_search" in names
            assert "wudao__watchlist_update" not in names
            assert kw["tool_executor"]("wudao__watchlist_update", {})["is_error"]
        else:
            assert not kw.get("tool_executor")
        source_call.assert_not_called()
        text = json.dumps({"summary": "test", "lessons": [{"hypothesis": "x", "evidence_ids": ["missing"], "validation_plan": "check"}]})
        return SimpleNamespace(stopped_reason="completed", finish_reason="stop", messages=[], text=text, model="test", input_tokens=1, output_tokens=1, rounds=1, invocations=[])
    monkeypatch.setattr("src.ai.application.agent.run_agent", run)
    with pytest.raises(ValueError, match="不存在的证据"):
        generate_review(SimpleNamespace(db_path="unused"), {"provider": "test", "model": "test"},
                        {"trade_date": "2026-09-14", "created_at": "2026-09-14T16:00:00+08:00", "evidence_ids": []})


@pytest.mark.parametrize('period,heading', [('premarket','盘前总计划'),('daily','全天复盘'),('weekly','本周复盘')])
def test_report_groups_each_stock_plans_once_with_verified_name(runtime,period,heading):
    from src.ops.application.guardian_review_format import report_sections, report_body
    context,generate,_=runtime
    guardian_review.execute_guardian_review({'period':'daily'},context)
    facts=generate.call_args.args[2]
    facts['period']=period
    code=facts['account']['positions'][0]['code']
    analysis={'summary':'整体评价', 'assessments':[], 'stock_reviews':[{'code':code,'assessment':'个股回顾'}],
              'plans':[{'code':code,'action':action,'quantity':100,'trigger':'触发'+action,'invalidation':'条件失效'} for action in ('hold','take_profit','stop_loss')], 'lessons':[]}
    sections=report_sections(facts,analysis)
    assert sections[1]['heading']==heading
    stocks=[s for s in sections if s['kind']=='stock']
    assert len(stocks)==1 and len(stocks[0]['plans'])==3
    assert stocks[0]['heading'].endswith('（'+code+'）')
    assert '个股回顾' in stocks[0]['paragraphs']
    body=report_body(facts,analysis)
    assert body.count(stocks[0]['heading'])==1 and body.index('个股回顾')<body.index('触发hold')<body.index('触发stop_loss')


@pytest.mark.parametrize('period,start,day,signal_day',[
    ('daily','2026-09-14','2026-09-14','2026-09-14'),
    ('premarket','2026-09-15','2026-09-15','2026-09-14'),
    ('weekly','2026-09-14','2026-09-18','2026-09-14'),
])
def test_reference_omitted_by_model_still_appears_for_all_report_periods(runtime,period,start,day,signal_day):
    from src.ops.application.guardian_review_format import report_sections
    context,generate,_=runtime
    guardian_review.execute_guardian_review({'period':'daily'},context)
    facts=generate.call_args.args[2]
    facts.update(period=period,start_date=start,trade_date=day,baseline_date='2026-09-14')
    facts['active_strategies']=[{'slug':'yangshi-tail-v1','name':'杨氏尾盘'}]
    facts['strategy_reference_pool']=[{'code':'301355','name':'南王科技','strategies':['yangshi-tail-v1'],
        'signals':[{'date':signal_day,'reason':'杨氏尾盘精选','timing':'次日开盘'}]},
        {'code':'300437','name':'清水源','strategies':['yangshi-tail-v1'],'signals':[{'date':'2026-09-08'}]}]
    sections=report_sections(facts,{'summary':'整体评价','plans':[]})
    coverage=next(s for s in sections if s['kind']=='references')
    assert '杨氏尾盘：南王科技（301355' in coverage['paragraphs'][0]
    assert '清水源' not in str(coverage)
    stock=next(s for s in sections if s['heading']=='南王科技（301355）')
    assert any('本轮模型未给出' in p for p in stock['paragraphs'])
    assert stock['plans']==[]


def test_reference_coverage_keeps_each_signal_strategy_and_does_not_claim_zero():
    from src.ops.application.guardian_review_references import reference_summary
    facts={'period':'daily','trade_date':'2026-09-14','active_strategies':[{'slug':'yangshi-tail-v1','name':'杨氏尾盘'},{'slug':'qianlong-close-v3','name':'潜龙'}],
           'strategy_reference_pool':[{'code':'301355','name':'南王科技','strategies':['yangshi-tail-v1','qianlong-close-v3'],
             'signals':[{'date':'2026-09-14','strategy_slug':'yangshi-tail-v1'},{'date':'2026-09-08','strategy_slug':'qianlong-close-v3'}]}]}
    rows=reference_summary(facts)
    assert '南王科技' in rows[0] and '南王科技' not in rows[1]
    assert '不据此断言' in rows[1]
