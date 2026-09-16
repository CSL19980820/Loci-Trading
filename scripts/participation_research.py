"""Participation correction: independent platform entries and confirmed pullback retests."""
import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.high_payoff_research import PERIODS, account
from scripts.limitup_rightside_research import attach_funds
from src.backtest import BacktestConfig, run_backtest


def eligible(item, policy):
    if policy.startswith('relative_'):
        base=item.get('origin')=='relative_index' and (policy.startswith('relative_control') or item['relative_leader'])
        if '_rising' in policy:base=base and item['index_now20_pct']>=0
        if '_falling' in policy:base=base and item['index_now20_pct']<0
        if '_shallow' in policy:base=base and item['leg_retrace_fraction']<=1/3
        if '_deep' in policy:base=base and item['leg_retrace_fraction']>1/3
        return base
    price_context = ((item['peer_return_pct'] or 0) > max(0, item['market_return_pct'])
                     and (item['peer_breadth'] or 0) >= .5)
    if item['market_breadth'] < .35:
        return False
    if policy == 'old_fund':
        return item['setup']=='pullback' and item['fund_confirmed'] and (item['peer_return_pct'] or 0)>0 and (item['peer_breadth'] or 0)>=.5
    if policy == 'hot_theme_platform':
        return (item['setup']=='platform' and price_context and (item['peer_breadth'] or 0)>=.55
                and item['theme_limitups_today']>=3 and item['theme_count_rank_fraction']<=.25)
    if policy == 'independent_platform':
        return item['setup']=='platform' and item['independent']
    if policy == 'pullback_retest' and item['setup']!='pullback':
        return False
    if policy == 'theme_platform' and item['setup']!='platform':
        return False
    return item['fund_confirmed'] or price_context or item['independent']


def make_events(payload, items, phase, hold, policy):
    dates=payload['dates'].tolist();ci={c:i for i,c in enumerate(payload['codes'].tolist())};di={d:i for i,d in enumerate(dates)}
    start,end=PERIODS[phase];phase_days=[d for d in dates if start<=d<=end];last=di[phase_days[-1]]
    events,marks,raw,factors,skips={},{},{},{},Counter()
    for item in items:
        day,code=item['signal_date'],item['code'];i,j=di[day],ci[code]
        if i+1>last:skips['end_without_entry']+=1;continue
        next_open=payload['open'][i+1,j]*payload['factor'][i+1,j]
        use_retest=item['setup']=='pullback' and policy!='old_fund' and not policy.endswith('_open')
        target=min(item['retest_level'],item['confirmation_close'])
        entry=min(next_open,target) if use_retest else next_open
        risk=(1-item['stop_level']/entry)*100 if entry>0 else np.nan
        cap=6 if policy=='old_fund' else 10
        if not np.isfinite(risk) or not (1.5 if policy=='old_fund' else 1)<=risk<=cap:skips['risk_distance']+=1;continue
        if next_open<=item['stop_level']:skips['open_below_support']+=1;continue
        if not use_retest and next_open/item['confirmation_close']-1>(.03 if policy=='old_fund' else .05):skips['opening_gap']+=1;continue
        days=dates[i:last+1];window=slice(i,last+1)
        panels={f:pd.DataFrame({code:payload[f][window,j]*payload['factor'][window,j]},index=days) for f in ['open','high','low','close']}
        panels['volume']=pd.DataFrame({code:payload['volume'][window,j]},index=days)
        signals=pd.DataFrame(False,index=days,columns=[code]);signals.iloc[0,0]=True
        entry_panel=pd.DataFrame(target,index=days,columns=[code]) if use_retest else None
        cfg=BacktestConfig(hold_days=hold,stop_loss_pct=-risk,take_profit_pct=2.5*risk if policy=='old_fund' else None,
                           commission_bps=3.1,stamp_duty_bps=5,slippage_bps=5,benchmark=None)
        result=run_backtest(signals,panels,entry_timing='next_dip' if use_retest else 'next_open',entry_price_panel=entry_panel,config=cfg)
        skips.update(result.skipped)
        if result.skipped.get('持有期内始终无法卖出'):raise ValueError('Unresolved held position')
        for trade in result.trades:
            events[(day,code)]={**asdict(trade),'risk_pct':risk,'setup':item['setup'],'fund_confirmed':item['fund_confirmed'],
                                'stop_level':item['stop_level'],'anchor_date':item['anchor_date']}
            # Retest fills must use the actual modeled limit fill, not the exchange open.
            factor=float(payload['factor'][i+1,j]);raw[(trade.entry_date,code)]=float(entry/factor);factors[(trade.entry_date,code)]=factor
        marks[code]=pd.Series(payload['close'][:,j]*payload['factor'][:,j],index=dates).ffill()
    return events,marks,raw,factors,phase_days,dict(skips)


def run(root,fund_root,policies=None,risk_budget=1000,holding_days=None):
    items=attach_funds(json.loads((root/'prepared/candidates.json').read_text(encoding='utf-8')),fund_root)
    payload=dict(np.load(root/'prepared/execution.npz'))
    results={}
    for phase,(start,end) in PERIODS.items():
        for policy in policies or ['old_fund','pullback_retest','theme_platform','combined','hot_theme_platform','independent_platform']:
            selected=[r for r in items if start<=r['signal_date']<=end and eligible(r,policy)]
            # Deduplicate before seeing fills/outcomes; prefer continuation over a retest on ties.
            unique={}
            for r in sorted(selected,key=lambda r:r['setup']=='platform'):
                unique[(r['signal_date'],r['code'])]=r
            selected=list(unique.values())
            choices=defaultdict(list)
            for r in selected:
                score=r['excess_now20_pp'] if policy.startswith('relative_') else (r['excess_five_day_pct'] if r['excess_five_day_pct'] is not None else r['daily_return_pct'])
                choices[r['signal_date']].append({**r,'score':score})
            for rows in choices.values():
                if policy.startswith('relative_'):
                    rows.sort(key=lambda r:(-r['score'],-r['excess_peak20_pp'],not r['fund_confirmed'],r['code']))
                else:
                    rows.sort(key=lambda r:(not r['fund_confirmed'],-r['score'],-r['anchor_amount'],r['code']))
                del rows[5:]
            # All candidate orders are committed before next-day execution outcomes.
            orders=[r for rows in choices.values() for r in rows]
            for hold in ([5] if policy=='old_fund' else holding_days or [10,20]):
                execution=make_events(payload,orders,phase,hold,policy)
                for cost in [1,2]:
                    result=account(choices,*execution[:4],execution[4],cost_multiplier=cost,max_positions=5,
                        slot_capital=40_000,risk_budget=risk_budget,max_per_theme=2,reserve_orders=True)
                    m=result['metrics'];daily=result['daily']
                    m['avg_exposure_pct']=float(np.mean([d['market_value']/d['equity'] for d in daily])*100)
                    m['holding_day_fraction_pct']=sum(d['open_positions']>0 for d in daily)/len(daily)*100
                    m['entry_days']=len({t['entry_date'] for t in result['trades']} | {t['entry_date'] for t in result['open_positions']})
                    result['funnel']={'eligible':len(selected),'ranked_orders':len(orders),'execution_skips':execution[5]}
                    key=f'{phase}/{policy}/hold{hold}/cost{cost}';results[key]=result
                    if cost==1:print(key,json.dumps(m),flush=True)
        if phase=='train':
            qualified=[k for k,v in results.items() if k.endswith('/cost1') and 'old_fund' not in k
                       and v['metrics']['trades']>=50 and v['metrics']['avg_exposure_pct']>=25
                       and v['metrics']['return_pct']>=15 and v['metrics']['max_drawdown_pct']>=-15
                       and (v['metrics']['profit_factor'] or 0)>=1.3]
            (root/'selection-before-validation.json').write_text(json.dumps({'qualified':qualified,
                'selected':max(qualified,key=lambda k:results[k]['metrics']['return_pct']) if qualified else None},indent=2),encoding='utf-8')
    (root/'results.json').write_text(json.dumps({'results':results,'protocol':'participation-correction-v1'},ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--fund-root',type=Path,required=True)
    p.add_argument('--policies',nargs='+')
    p.add_argument('--risk-budget',type=float,default=1000)
    p.add_argument('--holds',type=int,nargs='+')
    a=p.parse_args();run(a.root,a.fund_root,a.policies,a.risk_budget,a.holds)
