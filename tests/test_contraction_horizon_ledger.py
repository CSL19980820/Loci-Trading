"""Fixed-horizon observations are not cash-constrained portfolio trades."""
import numpy as np
import pandas as pd
import pytest

from scripts.contraction_horizon_ledger import build_ledger, summarize


def fixture():
    days = ['2025-01-23','2025-01-24','2025-01-27','2025-02-05','2025-02-06','2025-02-07']
    codes = ['000001','600001']
    base = pd.DataFrame(10.0,index=days,columns=codes)
    p = {'open':base.copy(), 'close':base.copy(), 'volume':base*0+100,
         '__adjust_factor':base*0+1}
    p['close'].iloc[2,0]=11
    p['close'].iloc[3,0]=9
    p['close'].iloc[4,0]=12
    picks=pd.DataFrame([{'signal_date':days[0],'rank':1,'code':'000001','name':'合成A'},
                        {'signal_date':days[0],'rank':2,'code':'600001','name':'合成B'},
                        {'signal_date':days[1],'rank':1,'code':'000001','name':'合成A'}])
    return days,p,picks


def test_uses_market_session_offsets_not_calendar_days():
    days,p,picks=fixture()
    r=build_ledger(picks,p,days)[0]
    assert r['entry_date']=='2025-01-24'
    assert r['t2_date']=='2025-01-27' and r['t3_date']=='2025-02-05'
    assert r['t4_date']=='2025-02-06'
    assert [r[f't{h}_gross_pct'] for h in [2,3,4]]==pytest.approx([10,-10,20])


def test_every_signal_retained_including_same_code_overlap():
    days,p,picks=fixture()
    rows=build_ledger(picks,p,days)
    assert len(rows)==3 and [r['code'] for r in rows]==['000001','600001','000001']
    assert len(set(r['notional'] for r in rows))==1


def test_no_stop_loss_or_limit_entry_filter():
    days,p,picks=fixture()
    p['open'].iloc[1,0]=11
    p['close'].iloc[2,0]=7
    p['close'].iloc[3,0]=13
    r=build_ledger(picks,p,days)[0]
    assert r['entry_status']=='ok'
    assert r['t2_gross_pct'] < -30
    assert r['t3_gross_pct'] > 18


def test_fixed_date_missing_is_not_replaced_by_later_price():
    days,p,picks=fixture()
    p['close'].iloc[2,0]=np.nan
    rows=build_ledger(picks,p,days)
    assert len(rows)==3
    assert rows[0]['t2_gross_pct'] is None
    assert rows[0]['t2_date']==days[2] and rows[0]['t3_gross_pct'] is not None
    stats=summarize(rows,'synthetic')
    assert stats[0]['missing']==1 and stats[0]['valid']==2


def test_nontraded_entry_is_retained_with_explicit_status():
    days,p,picks=fixture()
    p['volume'].iloc[1,0]=0
    r=build_ledger(picks,p,days)[0]
    assert r['entry_status']=='missing_or_nontraded_entry'
    assert all(r[f't{h}_gross_pct'] is None for h in [2,3,4])


def test_split_factor_normalizes_return_without_changing_raw_prices():
    days,p,picks=fixture()
    p['close'].iloc[2:,0]/=2
    p['__adjust_factor'].iloc[2:,0]=2
    r=build_ledger(picks,p,days)[0]
    assert r['t2_close']==5.5 and r['entry_open']==10
    assert r['t2_gross_pct']==pytest.approx(10)
    assert r['t2_raw_price_pct']==pytest.approx(-45)
    assert r['t2_adjustment_changed']


def test_summary_is_equal_weight_arithmetic_not_compounding():
    days,p,picks=fixture()
    rows=build_ledger(picks.iloc[:1],p,days)
    rows.append({**rows[0], 't2_gross_pct':-10.0,'t2_net_pct':-10.26,'t2_gross_pnl':-1000.0})
    stats=summarize(rows,'synthetic')[0]
    assert stats['mean_gross_pct']==pytest.approx(0)
    assert stats['mean_net_pct']==pytest.approx(-0.26)
    assert stats['equal_notional_gross_pnl']==pytest.approx(0)
    assert stats['win_rate_pct']==50


def test_notional_scales_cash_not_returns():
    days,p,picks=fixture()
    a,b=build_ledger(picks,p,days),build_ledger(picks,p,days,notional=20000)
    assert a[0]['t2_gross_pct']==b[0]['t2_gross_pct']
    assert 2*a[0]['t2_gross_pnl']==b[0]['t2_gross_pnl']


def test_more_than_two_daily_signals_rejected():
    days,p,picks=fixture()
    picks.loc[2,'signal_date']=days[0]
    picks.loc[2,'code']='600002'
    with pytest.raises(ValueError,match='exceeds two'):
        build_ledger(picks,p,days)


def test_insufficient_tail_calendar_rejected():
    days,p,picks=fixture()
    with pytest.raises(ValueError,match='four outcome'):
        build_ledger(picks,p,days[:4])
