"""Read-only retrospective Qianlong scoring diagnosis on a task-owned snapshot.

Run through tools/isolated_check.py. No provider requests, candidate writes,
strategy changes, accounts, scheduler mutations or production writes.
"""
from __future__ import annotations

import argparse
import copy
import gc
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.application.runner import prepare_backtest_context  # noqa: E402
from src.backtest.application.engine import run_backtest  # noqa: E402
from src.backtest.domain.models import BacktestConfig  # noqa: E402
from src.strategy.application.catalog import get  # noqa: E402
from tools.research_chinext_payoff_exits import (  # noqa: E402
    CutoffMarketStore, common_maturity_mask, execute_split_context, sha256,
)
from tools.research_chinext_payoff_filters import independent_metrics  # noqa: E402
from tools.research_multi_strategy_scoring import context_scores, SPECS  # noqa: E402
from tools.strategy_chinext_review import write_json, wilson_interval  # noqa: E402

VARIANTS = ('baseline', 'all_candidates', 'reverse_closeness', 'roc5', 'trend80')


def rank(mask, score, n=2):
    return mask & score.where(mask).rank(axis=1, ascending=False, method='first').le(n)


def metrics(trades, cost=.31):
    result = independent_metrics(trades, cost)
    result['win_rate_wilson_95_pct'] = wilson_interval(result)
    result['median_net_return'] = float(np.median([t.gross_return_pct-cost for t in trades])) if trades else None
    result['worst_net_return'] = min((t.gross_return_pct-cost for t in trades), default=None)
    result['stop_count'] = sum(t.exit_reason == 'stop_loss' for t in trades)
    return result


def interval_metrics(trades, start, end):
    return metrics([t for t in trades if start <= t.signal_date <= end])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    live = json.loads(args.context.read_text(encoding='utf-8'))
    latest = next(r for r in reversed(live['runs']) if r['status']=='success' and r.get('universe'))
    universe, params = latest['universe'], latest['effective_params']
    cutoff = live['cutoff']
    assert sha256(ROOT/'src/strategy/application/qianlong.py') == live['source_hashes']['src/strategy/application/qianlong.py']
    plan = {'cutoff':cutoff, 'revision':live['revision'], 'params':params, 'universe':universe,
            'source_context':str(args.context.resolve()),'snapshot_sha256':live['snapshot_sha256'],
            'variants':list(VARIANTS),'hold_days_after_entry':3,'stop_loss_pct':-7,'cost_pct':.31,
            'entry':'next_open','strict_limit_prices':True,'economic_returns':True,
            'selection':'fixed retrospective diagnostics; no parameter search or production changes',
            'sources':{p:sha256(ROOT/p) for p in ['tools/research_qianlong_recent.py', *live['source_hashes']]},
            'limitations':['Current catalog, names/ST and stored adjustment revisions; not strict PIT or survivor-free.',
                           'Historical data through May 2026 reuse the verified 2026-10-04 production snapshot; June onward refreshed read-only.',
                           'Independent signal events; no account NAV, capital capacity or actual Falcon fills.',
                           'All periods retrospective and already observed; alternative ranks are diagnostics, not fresh OOS.',
                           'Daily OHLC execution cannot establish exact intraday paths; historical receipts are partly missing.']}
    write_json(out/'PLAN.json',plan)
    summary, all_trades, candidate_rows, actual_rows, checks = {}, {}, [], [], []
    for year in (2024, 2025, 2026):
        start, end = f'{year}-01-01', cutoff if year==2026 else f'{year}-12-31'
        print(f'Prepare {year} full production universe',flush=True)
        cfg = BacktestConfig(hold_days=3, stop_loss_pct=-7., take_profit_pct=None,
                             commission_bps=3, stamp_duty_bps=5, slippage_bps=10,
                             strict_limit_prices=True,economic_returns=True,valuation_end=end,benchmark=None)
        engine = copy.copy(get('qianlong-close-v3'))
        engine.execution_adjust = 'none'
        engine.warmup_bars = 160
        with CutoffMarketStore(args.snapshot, end) as store:
            ctx = prepare_backtest_context(store,engine,start=start,end=end,params=params,
                                           universe=universe,adjust='qfq',config=cfg,source_evidence_mode='compact')
            computed = engine.compute(ctx['panels'],params)
            f, p = computed.factors, ctx['panels']
            eligible = f['条件候选'] & f['弱市可交易']
            native = f['白线贴近度']
            native_rank = native.where(eligible).rank(axis=1,ascending=False,method='first')
            scores, features = context_scores(p, native.mul(100).where(eligible), SPECS['qianlong-close-v3'])
            selected = {'baseline':computed.signals,'all_candidates':eligible,
                        'reverse_closeness':rank(eligible,-native),'roc5':rank(eligible,f['ROC5']),
                        'trend80':rank(eligible,scores['trend80'])}
            pd.testing.assert_frame_equal(rank(eligible,native),computed.signals)
            pd.testing.assert_frame_equal(computed.signals.loc[start:end],ctx['signals'].loc[start:end].fillna(False).astype(bool))
            prefix_end = p['close'].index[len(p['close'])//2]
            prefix = {k:v.loc[:prefix_end] if isinstance(v,pd.DataFrame) else v for k,v in p.items()}
            prefix_result = engine.compute(prefix,params)
            pd.testing.assert_frame_equal(prefix_result.signals,computed.signals.loc[:prefix_end])
            pd.testing.assert_frame_equal(prefix_result.factors['白线贴近度'],native.loc[:prefix_end])
            mature = common_maturity_mask(native.index,start,end,max_hold=4)
            window = (native.index>=start)&(native.index<=end)
            for i,j in zip(*np.nonzero(eligible.where(mature,False,axis=0).to_numpy())):
                date,code = str(native.index[i]),str(native.columns[j])
                candidate_rows.append({'signal_date':date,'code':code,'score':float(native.iat[i,j]*100),
                    'rank':int(native_rank.iat[i,j]),'candidate_count':int(eligible.iloc[i].sum()),
                    'breadth':float(f['市场上涨家数占比'].iat[i,j]),'turnover_pct':float(f['换手率(%)'].iat[i,j]),
                    'roc5':float(f['ROC5'].iat[i,j]),'repair':bool(features['repair'].iat[i,j]),
                    'uptrend':bool(features['uptrend'].iat[i,j]),'position120':float(features['position120'].iat[i,j]),
                    'board':ctx['resolved'].meta[code]['board_bucket'],'name':ctx['resolved'].meta[code].get('name','')})
            summary[str(year)] = {}
            for variant, mask in selected.items():
                run = execute_split_context({**ctx,'signals':mask},cfg,start,end,max_hold=4)
                trades = run['closed_trades']
                all_trades.setdefault(variant,[]).extend(trades)
                pd.DataFrame([t.to_dict() for t in run['all_trades']]).to_csv(out/f'{year}-{variant}-trades.csv',index=False)
                summary[str(year)][variant] = {'metrics':metrics(trades),'accounting':run['accounting'],
                    'double_cost':metrics(trades,.62),
                    'largest_winner_removed':metrics([t for t in trades if t is not max(trades,key=lambda t:t.net_return_pct)] if trades else [])}
                print(year,variant,json.dumps(summary[str(year)][variant]['metrics'],ensure_ascii=False),flush=True)
            checks.append({'year':year,'baseline_rank_equal':True,'baseline_runner_equal':True,'prefix_causality_equal':True,
                           'columns':len(native.columns),'universe_funnel':ctx['resolved'].funnel.to_dict(),
                           'dates':len(native.index),'pending_signal_count':int(computed.signals.loc[window].sum().sum())-int(computed.signals.where(mature,False,axis=0).sum().sum())})
            if year == 2026:
                days = [str(d) for d in native.index if str(d)<=cutoff]
                recent_starts = {'last20_sessions':days[-20],'last60_sessions':days[-60],'july':'2026-07-01','august':'2026-08-01','september':'2026-09-01','h1':'2026-01-01','h2':'2026-07-01'}
                ends = {'july':'2026-07-31','august':'2026-08-31','september':'2026-09-30','h1':'2026-06-30'}
                summary['recent'] = {name:{v:interval_metrics(all_trades[v],lo,ends.get(name,cutoff)) for v in VARIANTS} for name,lo in recent_starts.items()}
                summary['recent_ranges'] = {name:[lo,ends.get(name,cutoff)] for name,lo in recent_starts.items()}
                actual = pd.DataFrame(False,index=native.index,columns=native.columns)
                by_date = {}
                for r in live['runs']:
                    day=r.get('trade_date')
                    if r['status']=='success' and day and day<=cutoff:by_date.setdefault(day,r)
                for day,r in by_date.items():
                    for pick in r.get('picks') or []:
                        code=pick['code']
                        if code in actual.columns and day in actual.index:actual.at[day,code]=True
                    replay_codes=set(computed.signals.columns[computed.signals.loc[day]]) if day in computed.signals.index else set()
                    actual_rows.append({'signal_date':day,'run_id':r['id'],'revision':r.get('strategy_revision'),
                        'picks':[x['code'] for x in r.get('picks') or []], 'watch':[x['code'] for x in r.get('watch_picks') or []],
                        'replayed_picks':sorted(replay_codes),'same_picks':replay_codes=={x['code'] for x in r.get('picks') or []},
                        'breadth_saved':next((x['factors']['市场上涨家数占比'] for x in (r.get('picks') or [])+(r.get('watch_picks') or [])),None),
                        'breadth_replayed':float(f['市场上涨家数占比'].loc[day].iloc[0]) if day in native.index else None})
                actual_run = execute_split_context({**ctx,'signals':actual},cfg,start,end,max_hold=4)
                summary['actual_records'] = {'metrics':metrics(actual_run['closed_trades']),'accounting':actual_run['accounting']}
                pd.DataFrame([t.to_dict() for t in actual_run['all_trades']]).to_csv(out/'actual-record-trades.csv',index=False)
                write_json(out/'actual-run-comparison.json',actual_rows)
        del ctx, computed, p, f, eligible, native, native_rank, scores, features, selected
        gc.collect()
    candidates = pd.DataFrame(candidate_rows)
    raw = pd.DataFrame([t.to_dict() for t in all_trades['all_candidates']])
    labelled = candidates.merge(raw,on=['signal_date','code'],how='left',validate='one_to_one')
    if len(raw)!=len(labelled.dropna(subset=['net_return_pct'])):raise AssertionError('Candidate labels mismatch')
    baseline_keys = {(t.signal_date,t.code) for t in all_trades['baseline']}
    labelled['selected_baseline']=[(d,c) in baseline_keys for d,c in zip(labelled.signal_date,labelled.code)]
    # Gaps use economic prices, so dividend dates cannot manufacture high/low opens.
    labelled['entry_gap_pct']=np.nan
    with CutoffMarketStore(args.snapshot,cutoff) as store:
        for code, rows in labelled.groupby('code'):
            hist=store.history(code,start='2023-12-01',end=cutoff,adjust='hfq').set_index('trade_date')
            gaps=(hist['open']/hist['close'].shift(1)-1)*100
            labelled.loc[rows.index,'entry_gap_pct']=[float(gaps.get(d,np.nan)) for d in rows.entry_date]
    labelled.to_csv(out/'labelled-candidates.csv',index=False)
    summary['pooled'] = {v:metrics(all_trades[v]) for v in VARIANTS}
    for year in (2024,2025,2026):
        rows=labelled[labelled.signal_date.str.startswith(str(year))].dropna(subset=['net_return_pct'])
        summary[str(year)]['score_return_spearman']=float(rows.score.corr(rows.net_return_pct,method='spearman'))
        crowded=rows[rows.candidate_count>=3]
        summary[str(year)]['crowded_rank']={name:frame_stats(part) for name,part in [('top2',crowded[crowded['rank']<=2]),('rank3plus',crowded[crowded['rank']>2])]}
        summary[str(year)]['score_bins']={str(k):frame_stats(g) for k,g in rows.groupby(pd.cut(rows.score,[0,95,97,98,99,100]),observed=True)}
    selected_rows=labelled[labelled.selected_baseline].dropna(subset=['net_return_pct'])
    for label,rows in [('all',selected_rows),('last60',selected_rows[selected_rows.signal_date>=summary['recent_ranges']['last60_sessions'][0]])]:
        summary[f'diagnostics_{label}']={'gap_bins':{str(k):frame_stats(g) for k,g in rows.groupby(pd.cut(rows.entry_gap_pct,[-np.inf,0,2,5,np.inf]),observed=True)},
             'board':{str(k):frame_stats(g) for k,g in rows.groupby('board')},
             'repair':{str(k):frame_stats(g) for k,g in rows.groupby('repair')},
             'rank':{str(k):frame_stats(g) for k,g in rows.groupby('rank')}}
    summary['actual_full_observation'] = replay_actual_records(args.snapshot, live, out)
    write_json(out/'summary.json',summary)
    write_json(out/'verification.json',{'checks':checks,'candidate_count':len(candidates),'closed_labels':len(raw),
        'actual_run_count':len(actual_rows),'actual_picks_equal':sum(r['same_picks'] for r in actual_rows),
        'snapshot_sha256':sha256(args.snapshot),'plan_sha256':sha256(out/'PLAN.json')})
    print('Completed',str(out),flush=True)


def frame_stats(frame):
    values=frame.net_return_pct.dropna().to_numpy()
    wins,losses=values[values>0],values[values<=0]
    return {'trades':len(values),'wins':len(wins),'win_rate':float(len(wins)/len(values)*100) if len(values) else None,
            'avg_net_return':float(values.mean()) if len(values) else None,
            'median_net_return':float(np.median(values)) if len(values) else None,
            'profit_factor':float(wins.sum()/abs(losses.sum())) if len(losses) and losses.sum()<0 else None}


def replay_actual_records(snapshot, live, output):
    """Label recorded nominations, including early stops and pending positions."""
    first = {}
    for run in live['runs']:
        if run['status']=='success' and run.get('trade_date'):
            first.setdefault(run['trade_date'], run)
    picks = {(day,pick['code']):pick for day,run in first.items() for pick in run.get('picks') or []}
    codes = sorted({code for _,code in picks})
    cutoff = live['cutoff']
    cfg = BacktestConfig(hold_days=3,stop_loss_pct=-7.,commission_bps=3,stamp_duty_bps=5,
                         slippage_bps=10,benchmark=None,strict_limit_prices=True,
                         economic_returns=True,valuation_end=cutoff)
    with CutoffMarketStore(snapshot,cutoff) as store:
        dates = store.trading_days(start='2026-09-01',end=cutoff)
        raw = store.load_panel(fields=('open','high','low','close','volume'),codes=codes,start=dates[0],end=cutoff,adjust='none',min_bars=0)
        raw = {k:v.reindex(index=dates,columns=codes) for k,v in raw.items()}
        hfq = store.load_panel(fields=('close',),codes=codes,start=dates[0],end=cutoff,adjust='hfq',min_bars=0)['close'].reindex(index=dates,columns=codes)
        raw['__adjust_factor'] = (hfq/raw['close']).ffill()
        signals = pd.DataFrame(False,index=dates,columns=codes)
        for day,code in picks:signals.at[day,code]=True
        result = run_backtest(signals,raw,entry_timing='next_open',config=cfg,strategy_slug='qianlong-close-v3')
    labels = []
    trades = {(t.signal_date,t.code):t for t in result.trades}
    for (day,code),pick in picks.items():
        trade = trades.get((day,code))
        label = {'signal_date':day,'code':code,'name':pick['name'],'score':pick['factors']['白线贴近度']*100}
        if trade:
            label.update(trade.to_dict(include_factors=True))
            label['status'] = 'pending_position' if trade.exit_reason=='data_end' else 'closed'
        else:
            label['status'] = 'not_yet_entered' if day==cutoff else 'skipped'
        labels.append(label)
    pd.DataFrame(labels).to_csv(output/'actual-record-observation.csv',index=False)
    return {'labels':labels,'closed':sum(x['status']=='closed' for x in labels),
            'pending':sum(x['status']=='pending_position' for x in labels),
            'not_yet_entered':sum(x['status']=='not_yet_entered' for x in labels),'skipped':result.skipped,
            'note':'data_end values are mark-to-market observations, not completed trade outcomes'}


if __name__ == '__main__':
    main()
