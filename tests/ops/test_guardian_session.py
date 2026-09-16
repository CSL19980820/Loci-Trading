from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace
import pytest
from src.ops.application.guardian_session import in_review_window, review_slot, GUARDIAN_CRON
from src.ops.application.jobs import guardian
from src.ops.application.guardian_decision import parse_decision
from src.ledger import GuardianStore
from tests.ops.test_guardian import NOW, decision
from tests.ops import test_guardian

runtime = test_guardian.runtime


def test_requested_five_minute_slots_match_exact_session_boundaries():
    start=datetime(2026,9,14,9,tzinfo=ZoneInfo('Asia/Shanghai'))
    slots=[(start+timedelta(minutes=n)).strftime('%H:%M') for n in range(421) if n%5==0 and in_review_window(start+timedelta(minutes=n))]
    assert slots[0]=='09:25' and slots[-1]=='15:00' and len(slots)==51
    assert '11:30' in slots and '13:00' in slots and '11:35' not in slots and '12:55' not in slots
    assert not in_review_window(start.replace(day=19,hour=10))
    assert review_slot(start.replace(hour=10,minute=9,second=59)).endswith('10:05:00+08:00')
    from src.ops.infrastructure.scheduler import validate_cron
    fired=[]
    for trigger in validate_cron(GUARDIAN_CRON):
        previous=None
        value=trigger.get_next_fire_time(previous,start)
        while value.date()==start.date():
            fired.append(value.strftime('%H:%M'))
            previous=value
            value=trigger.get_next_fire_time(previous,value+timedelta(seconds=1))
    assert sorted(fired)==slots


@pytest.mark.parametrize('hour,minute',[(9,25),(11,30),(15,0)])
def test_boundary_rounds_are_recorded_without_fabricated_trades(runtime,monkeypatch,hour,minute):
    context,decide,notify=runtime
    now=NOW.replace(hour=hour,minute=minute)
    monkeypatch.setattr(guardian,'datetime',SimpleNamespace(now=lambda tz:now))
    result=guardian.execute_guardian({},context)
    assert decide.call_count==1 and result['analysis_only'] and result['deferred']
    assert result['fills']==[] and result['outcome']=='no_action'
    assert result['status']=='success' and result['blocked']==[]
    notify.assert_not_called()
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.trades()['total']==0 and ledger.recent()[0]['status']=='success'


def test_adjacent_five_minute_rounds_have_independent_identity(runtime,monkeypatch):
    context,decide,notify=runtime
    decide.return_value=(parse_decision('{"summary":"无动作","orders":[]}'),{})
    for minute in (0,5):
        monkeypatch.setattr(guardian,'datetime',SimpleNamespace(now=lambda tz,m=minute:NOW.replace(minute=m)))
        guardian.execute_guardian({},context)
    assert decide.call_count==2
    notify.assert_not_called()
    with GuardianStore(context.palace_db) as ledger:
        assert len(ledger.recent())==2


def test_model_finishing_after_market_close_retains_analysis_but_cannot_fill(runtime,monkeypatch):
    context,decide,notify=runtime
    clock=[NOW.replace(hour=14,minute=55)]
    monkeypatch.setattr(guardian,'datetime',SimpleNamespace(now=lambda tz:clock[0]))
    def late(*args,**kwargs):
        clock[0]=NOW.replace(hour=15,minute=1)
        return decision(),{}
    decide.side_effect=late
    result=guardian.execute_guardian({},context)
    assert result['fills']==[] and result['deferred'] and result['analysis_only']
    assert result['status']=='failed' and result['outcome']=='rejected'
    assert result['blocked'][0]['reject_code']=='execution_window'
    assert result['analysis']==decision().summary
    notify.assert_called_once()
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.trades()['total']==0
        assert ledger.recent()[0]['status']=='failed'


def test_terminal_owner_releases_orphan_but_live_owner_stays_locked(tmp_path):
    from src.ops.application.guardian_session import recover_finished_runs
    from unittest.mock import Mock
    with GuardianStore(tmp_path/'ledger.db') as ledger:
        assert ledger.claim('old-slot',run_id='old-run')
        store=Mock()
        store.get_run.return_value={'status':'running'}
        recover_finished_runs(ledger,store)
        assert not ledger.claim('new-slot')
        store.get_run.return_value={'status':'failed'}
        recover_finished_runs(ledger,store)
        assert ledger.claim('new-slot',run_id='new-run')
        assert ledger.trades()['total']==0
        assert ledger.running_cycles()[0]['result']['owner_run_id']=='new-run'
