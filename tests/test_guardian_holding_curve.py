from __future__ import annotations
import copy
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path.cwd()))
import pytest
from src.ledger.domain.guardian_account import new_guardian_account
from src.ledger.domain.guardian_curve import build_holding_curve, curve_snapshot
from src.ledger.infrastructure.guardian_curves import load_guardian_curve_evidence
from src.ledger.infrastructure.guardian_store import GuardianStore
from src.ledger.infrastructure.guardian_diary import GuardianDiaryStore
from src.ops.application.guardian_holding_curve import protection_summary

TZ = ZoneInfo('Asia/Shanghai')
DAY = datetime(2026, 9, 21, 10, 0, tzinfo=TZ)
CODE = '600000'

class Ledger:
    def __init__(self):
        self.state = new_guardian_account()
        self.trades = []
        self.snapshots = []
        self.at = DAY
    def position(self):
        return next((p for p in self.state['positions'] if p['code'] == CODE), None)
    def mark(self, px, *, fresh=True, step=60):
        self.at += timedelta(seconds=step)
        for p in self.state['positions']:
            p.update(mark_price_cents=px, mark_at=(self.at-timedelta(seconds=30 if fresh else 1000)).isoformat(),
                     mark_source='fixture', valuation_stale=not fresh)
        self.state.update(valuation_at=self.at.isoformat(), valuation_kind='live',
            stale_codes=[] if fresh else [CODE],
            market_value_cents=sum(p['quantity'] * px for p in self.state['positions']))
        self.state['equity_cents'] = self.state['cash_cents'] + self.state['market_value_cents']
        self.snapshots.append({'state': copy.deepcopy(self.state), 'source':'fixture'})
    def trade(self, side, q, px=1000, fee=0):
        self.at += timedelta(seconds=60)
        p = self.position()
        before = p['quantity'] if p else 0
        gross = q*px
        allocated = (p['cost_cents']*q + before//2)//before if side == 'sell' else 0
        realized = gross-fee-allocated if side == 'sell' else 0
        self.state['cash_cents'] += gross-fee if side == 'sell' else -gross-fee
        self.state['fees_cents'] += fee
        self.state['realized_pnl_cents'] += realized
        if not p:
            p={'code':CODE,'name':'布局测试','quantity':0,'cost_cents':0,'entry_context':{'opened_at':self.at.isoformat()},'today_bought':0}
            self.state['positions'].append(p)
        p['quantity'] += q if side=='buy' else -q
        p['cost_cents'] += gross+fee if side=='buy' else -allocated
        after=p['quantity']
        self.trades.append({'id':str(len(self.trades)), 'occurred_at':self.at.isoformat(), 'code':CODE,
            'name':p['name'], 'side':side,'action':side,'quantity':q,'price_cents':px,
            'gross_cents':gross,'fees_cents':fee,'allocated_cost_cents':allocated,
            'realized_pnl_cents':realized,'before_quantity':before,'after_quantity':after,
            'cash_after_cents':self.state['cash_cents'],'quote_at':self.at.isoformat()})
        if after==0:self.state['positions'].remove(p)
        self.mark(px,step=1)
    def evidence(self):
        return {'state':copy.deepcopy(self.state),'trades':copy.deepcopy(self.trades),'snapshots':copy.deepcopy(self.snapshots)}
    def curve(self, code=CODE, **kwargs):
        return build_holding_curve(self.evidence(),code=code,now=self.at,**kwargs)

def test_price_peak_drawdown_and_recovery():
    l=Ledger();l.trade('buy',100);l.mark(1200);l.mark(1080)
    c=l.curve()
    assert c['summary']['max_drawdown_pct']==pytest.approx(-10)
    assert c['summary']['current_drawdown_pct']==pytest.approx(-10)
    assert c['summary']['recovery_pct']==pytest.approx(11.111111)
    assert c['summary']['latest_pnl_cents']==8000

def test_add_at_same_price_does_not_fake_gain():
    l=Ledger();l.trade('buy',100);l.mark(1200);l.trade('buy',500,1200)
    c=l.curve();assert c['summary']['latest_nav']==pytest.approx(1.2)
    assert c['summary']['max_drawdown_pct']==0
    assert c['summary']['latest_pnl_cents']==20000

def test_reduce_at_same_price_does_not_fake_drawdown():
    l=Ledger();l.trade('buy',1000);l.mark(1200);l.trade('sell',900,1200)
    c=l.curve();assert c['summary']['latest_nav']==pytest.approx(1.2)
    assert c['summary']['max_drawdown_pct']==0
    assert c['summary']['latest_pnl_cents']==200000
    assert l.curve(code='')['summary']['max_drawdown_pct']==0

def test_fees_reduce_nav_and_pnl():
    l=Ledger();l.trade('buy',100,1000,100);l.trade('sell',50,1000,50)
    c=l.curve()
    assert c['summary']['latest_pnl_cents']==-150
    assert c['summary']['latest_nav']==pytest.approx((100000/100100)*(99950/100000))
    assert -0.2<c['summary']['max_drawdown_pct']<0

def test_reopen_has_new_episode_and_no_old_loss():
    l=Ledger();l.trade('buy',100);l.trade('sell',100,500);l.trade('buy',100,1000)
    c=l.curve();assert c['summary']['latest_pnl_cents']==0
    assert c['summary']['max_drawdown_pct']==0
    assert c['opened_at']==l.trades[-1]['occurred_at']

def test_stale_quote_is_gap_not_zero():
    l=Ledger();l.trade('buy',100);l.mark(1200);l.mark(1,fresh=False)
    c=l.curve();assert c['points'][-1]['nav'] is None
    assert c['summary']['current_drawdown_pct'] is None
    assert c['summary']['max_drawdown_pct']==0

@pytest.mark.parametrize('px',[0,-1,True,float('nan')])
def test_bad_price_does_not_generate_false_drawdown(px):
    l=Ledger();l.trade('buy',100);e=l.evidence();e['state']['positions'][0]['mark_price_cents']=px
    c=build_holding_curve(e,code=CODE,now=l.at)
    assert c['summary']['current_drawdown_pct'] is None
    assert c['summary']['max_drawdown_pct']==0

def test_expired_current_quote_keeps_historical_high():
    l=Ledger();l.trade('buy',100);l.mark(1200);l.mark(1100)
    c=build_holding_curve(l.evidence(),code=CODE,now=l.at+timedelta(minutes=10))
    assert c['summary']['current_drawdown_pct'] is None
    assert c['summary']['max_drawdown_pct']==pytest.approx(-100/12)
    assert c['summary']['last_valid_drawdown_pct']==pytest.approx(-100/12)

def test_cash_mismatch_fails_closed():
    l=Ledger();l.trade('buy',100);e=l.evidence();e['trades'][0]['cash_after_cents']+=1
    with pytest.raises(ValueError,match='现金'):build_holding_curve(e,code=CODE,now=l.at)

def test_current_cost_mismatch_fails_closed():
    l=Ledger();l.trade('buy',100);e=l.evidence();e['state']['positions'][0]['cost_cents']+=1
    with pytest.raises(ValueError,match='不一致'):build_holding_curve(e,code=CODE,now=l.at)

def test_snapshot_quantity_mismatch_is_gap():
    l=Ledger();l.trade('buy',100);l.mark(1200);e=l.evidence();e['snapshots'][-1]['state']['positions'][0]['quantity']=1000
    e['snapshots'][-1]['state']['valuation_at']=(l.at-timedelta(seconds=1)).isoformat()
    c=build_holding_curve(e,code=CODE,now=l.at)
    assert c['excluded_points']>=1
    assert c['summary']['max_drawdown_pct']==0

def test_window_peak_does_not_include_previous_window():
    l=Ledger();l.trade('buy',100);l.mark(1200);l.at+=timedelta(days=2);l.mark(1000);l.mark(1100)
    c=l.curve(days=1);assert c['summary']['max_drawdown_pct']==0
    assert all(p['at'].startswith('2026-09-23') for p in c['points'])

def test_empty_account_not_fabricated_history():
    c=build_holding_curve({'state':new_guardian_account(),'trades':[],'snapshots':[]},now=DAY)
    assert len(c['points'])==1
    assert c['summary']['max_drawdown_pct'] is None

def test_all_points_time_ordered():
    l=Ledger();l.mark(1000);l.trade('buy',100)
    c=l.curve(code='');assert [p['at'] for p in c['points']]==sorted(p['at'] for p in c['points'])

def test_snapshot_does_not_keep_prompt_or_risk_contract():
    l=Ledger();l.trade('buy',100);l.state['prompt']='secret';l.position()['risk_plans']=[{'private':'secret'}]
    assert 'secret' not in json.dumps(curve_snapshot(l.state))

def test_reader_creates_no_database(tmp_path):
    p=tmp_path/'absent.db';load_guardian_curve_evidence(db_path=p)
    assert not p.exists()

def test_reader_does_not_change_data_and_returns_bound_snapshot(tmp_path):
    p=tmp_path/'fixture.db';l=Ledger();l.trade('buy',100);l.mark(1200)
    with GuardianStore(p) as store:
        store.conn.execute('UPDATE guardian_portfolio SET state_json=?',(json.dumps(l.state),))
        for f in l.trades:store.conn.execute('INSERT INTO guardian_trades VALUES(?,?,?,?,?)',(f['id'],f['occurred_at'],CODE,f['occurred_at'],json.dumps(f)))
        for n,s in enumerate(l.snapshots):store.conn.execute('INSERT INTO guardian_cycles VALUES(?,?,?,?)',(s['state']['valuation_at'],n,'success',json.dumps({'curve_snapshot':curve_snapshot(s['state'])})))
        store.conn.commit()
    before=hashlib.sha256(p.read_bytes()).hexdigest();e=load_guardian_curve_evidence(db_path=p,now=l.at)
    assert build_holding_curve(e,code=CODE,now=l.at)['summary']['latest_nav']==pytest.approx(1.2)
    assert hashlib.sha256(p.read_bytes()).hexdigest()==before
    p.unlink() # The reader must release the connection on Windows too.

def test_daily_cleanup_preserves_curve_facts(tmp_path):
    p=tmp_path/'fixture.db';l=Ledger();l.trade('buy',100)
    with GuardianDiaryStore(p) as store:
        for n in range(65):
            at=(DAY-timedelta(days=70-n)).isoformat()
            s=copy.deepcopy(l.state);s['valuation_at']=at
            store.conn.execute('INSERT INTO guardian_cycles VALUES(?,?,?,?)',(at,n,'success',json.dumps({'account':s,'decision_context':{'account_before':s,'prompt':'discard me'},'analysis':'test'})))
        store.conn.commit();store.save_preferences({'days':1,'max_entries':40,'cleanup_hours':24})
        out=store.compact(now=DAY,force=True)
        assert out['removed']>0
        row=json.loads(store.conn.execute('SELECT result_json FROM guardian_cycles ORDER BY slot LIMIT 1').fetchone()[0])
        assert row['curve_snapshot']['positions'][0]['quantity']==100
        assert 'decision_context' not in row and 'discard me' not in json.dumps(row)

def test_protection_report_is_read_only_and_shows_tplusone():
    l=Ledger();l.trade('buy',100);p=l.position();p['today_bought']=100;p['bought_on']=DAY.date().isoformat()
    before=copy.deepcopy(l.state);r=protection_summary(l.state,l.at)[0]
    assert r['unprotected_quantity']==100 and r['locked_quantity']==100
    assert l.state==before

def test_invalid_numbers_still_serialize():
    l=Ledger();l.trade('buy',100);e=l.evidence();e['state']['positions'][0]['mark_price_cents']=float('nan')
    result=build_holding_curve(e,code=CODE,now=l.at)
    json.dumps(result,allow_nan=False)

def test_active_stop_can_be_diagnosed_without_execution():
    from src.ops.application.guardian_risk import install_risk_plans
    l=Ledger();l.trade('buy',100);l.mark(900)
    install_risk_plans(l.position(),[{'action':'stop_loss','quantity':100,'trigger_price':9.5,
        'execution':{'kind':'market','valid_until':(l.at+timedelta(hours=1)).isoformat()},'reason':'isolated test'}],l.at)
    before=copy.deepcopy(l.state);r=protection_summary(l.state,l.at)[0]
    assert not r['stale'] and r['stops'][0]['reached'] and r['unprotected_quantity']==0
    assert l.state==before
    expired=protection_summary(l.state,l.at+timedelta(hours=2))[0]
    assert expired['protected_quantity']==0 and expired['invalid_plans']==1
    assert l.state==before

def test_finish_saves_minimal_valuation_with_existing_atomic_guards(tmp_path):
    l=Ledger();l.trade('buy',100)
    with GuardianStore(tmp_path/'fixture.db') as store:
        assert store.claim(l.at.isoformat(),run_id='owned')
        store.finish(l.at.isoformat(),{'status':'success','fills':l.trades},l.state,run_id='owned')
        saved=json.loads(store.conn.execute('SELECT result_json FROM guardian_cycles').fetchone()[0])
        assert saved['curve_snapshot']['positions'][0]['quantity']==100
        assert 'risk_plans' not in saved['curve_snapshot']['positions'][0]
        with pytest.raises(RuntimeError):store.finish(l.at.isoformat(),{'status':'success'},l.state,run_id='owned')
        slot=(l.at+timedelta(minutes=1)).isoformat();assert store.claim(slot,run_id='second')
        bad=copy.deepcopy(l.state);bad['cash_cents']+=100;bad['realized_pnl_cents']+=100
        with pytest.raises(ValueError):store.finish(slot,{'status':'success'},bad,run_id='second')
        assert store.state()['cash_cents']==l.state['cash_cents']
        row=store.conn.execute('SELECT status,result_json FROM guardian_cycles WHERE slot=?',(slot,)).fetchone()
        assert row[0]=='running' and 'curve_snapshot' not in json.loads(row[1])

def test_curve_visitor_policy_is_read_only():
    from src.app.visitor_access import visitor_allowed
    assert visitor_allowed('GET','/api/ops/guardian/holding-curve')
    for verb in ('POST','PUT','PATCH','DELETE'):
        assert not visitor_allowed(verb,'/api/ops/guardian/holding-curve')

@pytest.mark.parametrize('query',['days=0','days=367','code=../data','code=0000011','code=600000%27'])
def test_query_validation_never_reaches_reader(query,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ops.api.guardian_reads import build_guardian_reads_router
    import src.ops.application.guardian_holding_curve as service
    def forbidden(**kwargs):raise AssertionError('Reader must not run for bad query')
    monkeypatch.setattr(service,'get_holding_curve',forbidden)
    app=FastAPI();app.include_router(build_guardian_reads_router())
    with TestClient(app) as client:assert client.get('/holding-curve?'+query).status_code==422
