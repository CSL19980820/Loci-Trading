import numpy as np
import pandas as pd

from scripts.high_payoff_research import account
from scripts.participation_prepare import platform_features
from scripts.participation_research import make_events


def test_platform_can_form_without_pullback_and_is_prefix_causal():
    frame=pd.DataFrame({'open':10.,'high':10.1,'low':9.9,'close':10.,'volume':10_000_000.,'factor':1.},index=pd.bdate_range('2026-01-01',periods=90))
    frame.iloc[70]=[10.1,10.4,10.05,10.3,20_000_000.,1.]
    before=platform_features(frame)
    assert before.signal.iloc[70]
    frame.iloc[71:,0:4]*=100
    pd.testing.assert_frame_equal(before.iloc[:71],platform_features(frame).iloc[:71])


def test_unfilled_first_limit_order_does_not_free_slot_for_future_winner():
    dates=['2026-02-02','2026-02-03','2026-02-04']
    choices={dates[0]:[{'code':'A','name':'A','score':2},{'code':'B','name':'B','score':1}]}
    events={(dates[0],'B'):{'entry_date':dates[1],'exit_date':dates[2],'exit_reason':'hold_expired','gross_return_pct':100.}}
    marks={'B':pd.Series([10.,10.,20.],index=dates)}
    r=account(choices,events,marks,{(dates[1],'B'):10.},{(dates[1],'B'):1.},dates,max_positions=1,reserve_orders=True)
    assert r['metrics']['trades']==0
    assert r['metrics']['ending_equity']==200000
    assert r['skipped']['order_slots_reserved']==1


def test_retest_uses_limit_fill_for_share_sizing_and_does_not_fill_untouched():
    dates=pd.bdate_range('2026-02-02',periods=8).strftime('%Y-%m-%d').to_numpy()
    payload={'dates':dates,'codes':np.array(['600001'])}
    for f,v in {'open':100.,'high':102.,'low':97.,'close':100.,'volume':1000000.,'factor':1.}.items():payload[f]=np.full((8,1),v)
    row={'code':'600001','signal_date':str(dates[0]),'setup':'pullback','retest_level':98.,'confirmation_close':100.,'stop_level':90.,'anchor_date':str(dates[0]),'fund_confirmed':True}
    events,_,raw,*_=make_events(payload,[row],'validation',10,'pullback_retest')
    assert events[(str(dates[0]),'600001')]['entry_price']==98.
    assert raw[(str(dates[1]),'600001')]==98.
    payload['low'][1,0]=99.
    assert make_events(payload,[row],'validation',10,'pullback_retest')[0]=={}
