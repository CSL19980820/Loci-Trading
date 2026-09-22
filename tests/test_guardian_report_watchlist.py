import pytest
from src.ledger import GuardianStore
from src.ops.application.guardian_context import reference_days, observe


def test_three_completed_exchange_days_and_explicit_watch_survives_window():
    days = reference_days('2026-09-22')
    assert days == ['2026-09-17', '2026-09-18', '2026-09-21']
    class Palace:
        def candidates_payload(self, day):
            return [{'code':'600001','name':'近期','date':day,'strategy_slug':'quant','decision':'精选'}]
    rows = observe(Palace(), days, {'positions': [], 'watchlist':[{'code':'600000','name':'主动保留'}]}, [])
    assert {s['date'] for r in rows for s in r['signals']} == set(days)
    assert next(r for r in rows if r['code']=='600000')['watch']['name'] == '主动保留'


@pytest.mark.parametrize('period', ['daily', 'premarket'])
def test_report_observation_updates_atomic_and_never_trade(tmp_path, period):
    with GuardianStore(tmp_path/'palace.db') as store:
        before = store.state()
        token = store.claim_report(period, '2026-09-21')
        result = {'status':'success','created_at':'2026-09-21T18:00:00+08:00',
                  'facts':{'stock_names':{'600000':'主动选择'}},
                  'analysis':{'watchlist_updates':[{'code':'600000','action':'watch','reason':'继续研究'}]}}
        with pytest.raises(RuntimeError):
            store.finish_report(period, '2026-09-21', 'stale', result)
        assert store.state() == before
        store.finish_report(period, '2026-09-21', token, result)
        after = store.state()
        assert after['watchlist'][0]['name'] == '主动选择'
        assert {k:v for k,v in after.items() if k!='watchlist'} == {k:v for k,v in before.items() if k!='watchlist'}
        assert store.trades()['total'] == 0
        token = store.claim_report(period, '2026-09-22')
        result['analysis']['watchlist_updates'] = [{'code':'600000','action':'unwatch','reason':'不再关注'}]
        store.finish_report(period, '2026-09-22', token, result)
        assert store.state()['watchlist'] == []


def test_cancel_quant_reference_is_not_readded_until_new_signal_or_explicit_watch():
    from src.ledger.domain.guardian_watchlist import update_watchlist
    state = {'positions': []}
    class Palace:
        def candidates_payload(self, day):
            return [{'code':'600000','name':'候选','date':day,'strategy_slug':'quant','decision':'精选'}]
    update_watchlist(state, {'code':'600000','action':'unwatch','reason':'暂不关注'}, '2026-09-21T10:00:00+08:00')
    assert observe(Palace(), ['2026-09-18','2026-09-21'], state, []) == []
    assert observe(Palace(), ['2026-09-22'], state, [])[0]['code'] == '600000'
    update_watchlist(state, {'code':'600000','action':'watch','reason':'重新纳入'}, '2026-09-21T11:00:00+08:00')
    assert observe(Palace(), ['2026-09-21'], state, [])[0]['watch']['reason'] == '重新纳入'


def test_window_is_same_for_previous_close_and_next_premarket():
    from datetime import datetime
    from src.ops.application.guardian_context import reference_target_day
    for stamp in ('2026-09-21T16:00:00+08:00', '2026-09-22T08:50:00+08:00', '2026-09-22T09:25:00+08:00'):
        target = reference_target_day(datetime.fromisoformat(stamp))
        assert target == '2026-09-22'
        assert reference_days(target) == ['2026-09-17','2026-09-18','2026-09-21']
    assert reference_target_day(datetime.fromisoformat('2026-09-19T10:00:00+08:00')) == '2026-09-21'
    assert reference_days('2026-09-21') == ['2026-09-16','2026-09-17','2026-09-18']
