"""模型选留仓、程序按真实报价收敛；部分失败不能丢账或闭市后造单。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ledger import GuardianStore, new_guardian_account
from src.ops.application.jobs import guardian
from src.ops.application.jobs.context import JobError
from tests.ledger.test_guardian_position_limit import apply, buy, NOW, OLD, NEW
from tests.ops import test_guardian

runtime = test_guardian.runtime


def seed(context):
    with GuardianStore(context.palace_db) as ledger:
        state, fills, rejects = apply(new_guardian_account(), [buy(c) for c in OLD])
        assert not rejects and ledger.claim('seed-old')
        ledger.finish('seed-old', {'status': 'success', 'fills': fills}, state)
        state, fills, rejects = apply(state, [buy(c) for c in NEW], day=15, keep=NEW)
        assert not rejects and ledger.claim('seed-new')
        ledger.finish('seed-new', {'status': 'success', 'fills': fills}, state)


def setup_close(runtime, monkeypatch):
    context, decide, notify = runtime
    seed(context)
    clock = [NOW.replace(day=15, hour=14, minute=50)]
    monkeypatch.setattr(guardian, 'datetime', SimpleNamespace(now=lambda tz: clock[0]))
    monkeypatch.setattr(context, 'market', Mock(side_effect=AssertionError('收敛不依赖候选池研究')))
    decide.side_effect = AssertionError('已保存模型留仓选择，尾盘执行不再等待模型')
    def snapshot(codes, **kw):
        return SimpleNamespace(quotes={c: {'code': c, 'price': 10, 'trade_date': '2026-09-15',
                                         'trade_time': clock[0].strftime('%H:%M:%S')} for c in codes})
    monkeypatch.setattr(guardian, 'build_monitor_snapshot', snapshot)
    return context, decide, notify, clock, snapshot


def test_stored_model_choice_closes_eight_to_four_without_new_research(runtime, monkeypatch):
    context, decide, notify, _, _ = setup_close(runtime, monkeypatch)
    result = guardian.execute_guardian({}, context)
    assert result['closing_rebalance'] and not result['closing_pending']
    assert len(result['fills']) == 4 and {f['code'] for f in result['fills']} == set(OLD)
    decide.assert_not_called()
    notify.assert_called_once()
    with GuardianStore(context.palace_db) as ledger:
        assert {p['code'] for p in ledger.state()['positions']} == set(NEW)
        assert ledger.trades()['total'] == 12


def test_partial_close_is_committed_and_only_remaining_exit_retries(runtime, monkeypatch):
    context, decide, notify, clock, snapshot = setup_close(runtime, monkeypatch)
    def partial(codes, **kw):
        value = snapshot(codes, **kw)
        value.quotes.pop(OLD[0], None)
        return value
    monkeypatch.setattr(guardian, 'build_monitor_snapshot', partial)
    with pytest.raises(JobError, match='尚未收敛'):
        guardian.execute_guardian({}, context)
    with GuardianStore(context.palace_db) as ledger:
        assert len(ledger.state()['positions']) == 5 and ledger.trades()['total'] == 11
        failed = ledger.recent()[0]
        assert failed['status'] == 'failed' and len(failed['result']['fills']) == 3
        assert failed['result']['closing_pending']
    clock[0] = clock[0].replace(minute=55)
    monkeypatch.setattr(guardian, 'build_monitor_snapshot', snapshot)
    result = guardian.execute_guardian({}, context)
    assert len(result['fills']) == 1 and result['fills'][0]['code'] == OLD[0]
    with GuardianStore(context.palace_db) as ledger:
        assert len(ledger.state()['positions']) == 4 and ledger.trades()['total'] == 12
    decide.assert_not_called()
    assert notify.call_count == 2


def test_quote_finishing_after_close_is_failed_without_fabricated_fill(runtime, monkeypatch):
    context, decide, notify, clock, snapshot = setup_close(runtime, monkeypatch)
    def late(codes, **kw):
        clock[0] = clock[0].replace(hour=15, minute=1)
        return snapshot(codes, **kw)
    monkeypatch.setattr(guardian, 'build_monitor_snapshot', late)
    with pytest.raises(JobError, match='尚未收敛'):
        guardian.execute_guardian({}, context)
    with GuardianStore(context.palace_db) as ledger:
        assert len(ledger.state()['positions']) == 8 and ledger.trades()['total'] == 8
        failed = ledger.recent()[0]['result']
        assert failed['analysis_only'] and len(failed['deferred']) == 4 and failed['fills'] == []
    decide.assert_not_called()
    notify.assert_called_once()
