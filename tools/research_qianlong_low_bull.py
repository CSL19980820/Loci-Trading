"""Frozen low-bull frequency expansion on a read-only Qianlong snapshot.

Filters the complete eligible universe before native Top2 ranking. No source,
production, candidate-store, account, scheduler or deployment mutations.
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
from src.backtest.domain.models import BacktestConfig  # noqa: E402
from src.strategy.application.catalog import get  # noqa: E402
from tools.research_chinext_payoff_exits import (  # noqa: E402
    CutoffMarketStore, common_maturity_mask, execute_split_context, sha256,
)
from tools.research_impulse_scoring import now, paired_bootstrap  # noqa: E402
from tools.research_qianlong_optimization import SPLITS, rank, variant_bundle  # noqa: E402
from tools.research_qianlong_recent import metrics  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

VARIANTS = ('baseline', 'long_bull', 'low_range_bull', 'prior20_lower',
            'prior60_lower', 'support_retest', 'near_ma60', 'base_repair', 'rising_floor')
CONTROLS = ('baseline', 'long_bull', 'low_range_bull')
PARENT_STUDY = ROOT/'docs/research/2026-10-12-qianlong-trend-shapes'


def structure_features(panels):
    close, high, low = (panels[k] for k in ('close', 'high', 'low'))
    ma = {n:close.rolling(n).mean() for n in (20,60,120)}
    prior_low = low.where(low.gt(0) & np.isfinite(low)).shift(1)
    prior_high = high.where(high.gt(0) & np.isfinite(high)).shift(1)
    lo = {n:prior_low.rolling(n).min() for n in (20,60,120)}
    hi = {n:prior_high.rolling(n).max() for n in (20,60,120)}
    pos = {n:(close.shift(1) if n in (20,60) else close).sub(lo[n]).div((hi[n]-lo[n]).where(hi[n].gt(lo[n])))
           for n in (20,60,120)}
    ratio60 = (low/ma[60]).where(low.gt(0) & np.isfinite(low)).shift(1)
    retest_min, retest_max = ratio60.rolling(10).min(), ratio60.rolling(10).max()
    floor_recent5 = prior_low.rolling(5).min()
    floor_older5 = low.where(low.gt(0) & np.isfinite(low)).shift(6).rolling(5).min()
    known_base = np.isfinite(close) & close.gt(0)
    for n in (60,120):known_base &= np.isfinite(ma[n]) & np.isfinite(ma[n].shift(20))
    long_bull = close.gt(ma[60]) & ma[60].gt(ma[120]) & ma[60].gt(ma[60].shift(20)) & ma[120].ge(ma[120].shift(20))
    known_position = {n:known_base & np.isfinite(pos[n]) for n in pos}
    known_retest = known_base & np.isfinite(retest_min) & np.isfinite(retest_max)
    known_repair = known_position[120] & np.isfinite(ma[20]) & np.isfinite(ma[20].shift(5))
    known_floor = known_base & np.isfinite(ma[20]) & np.isfinite(floor_recent5) & np.isfinite(floor_older5)
    conditions = {
        'baseline':pd.DataFrame(True,index=close.index,columns=close.columns),
        'long_bull':long_bull,
        'low_range_bull':long_bull & pos[120].ge(0) & pos[120].le(.4),
        'prior20_lower':long_bull & pos[20].ge(0) & pos[20].le(.5),
        'prior60_lower':long_bull & pos[60].ge(0) & pos[60].le(.5),
        'support_retest':long_bull & retest_min.ge(.98) & retest_min.le(1.03),
        'near_ma60':long_bull & close.le(1.08*ma[60]),
        'base_repair':close.gt(ma[20]) & ma[20].gt(ma[60]) & ma[20].gt(ma[20].shift(5))
             & ma[60].gt(ma[60].shift(20)) & ma[120].ge(.99*ma[120].shift(20))
             & close.le(1.10*ma[120]) & pos[120].ge(0) & pos[120].le(.6),
        'rising_floor':long_bull & floor_recent5.ge(1.01*floor_older5) & close.le(1.05*ma[20]),
    }
    known = {'baseline':conditions['baseline'],'long_bull':known_base,'low_range_bull':known_position[120],
             'prior20_lower':known_position[20],'prior60_lower':known_position[60],
             'support_retest':known_retest,'near_ma60':known_base,'base_repair':known_repair,'rising_floor':known_floor}
    gates = {name:(condition & known[name]).fillna(False) for name,condition in conditions.items()}
    features = {f'ma{n}':value for n,value in ma.items()}
    features.update({f'ma{n}_lag20':ma[n].shift(20) for n in (60,120)})
    features.update({f'prior_low{n}':value for n,value in lo.items()})
    features.update({f'prior_high{n}':value for n,value in hi.items()})
    features.update({f'position{n}':value for n,value in pos.items()})
    features.update({'ma20_lag5':ma[20].shift(5),'close':close,'previous_close':close.shift(1),
                     'past10_min_low_ma60':retest_min,'past10_max_low_ma60':retest_max,
                     'floor_recent5':floor_recent5,'floor_older5':floor_older5})
    return gates, known, features



def source_hashes():
    paths = ['tools/research_qianlong_low_bull.py','tools/research_qianlong_trend_shapes.py','tools/research_qianlong_optimization.py',
             'tools/research_qianlong_recent.py','tools/research_chinext_payoff_exits.py',
             'tools/research_impulse_scoring.py','src/strategy/application/qianlong.py',
             'src/backtest/application/runner.py','src/backtest/application/engine.py',
             'src/market/infrastructure/store_panel.py']
    return {p:sha256(ROOT/p) for p in paths}


def frequency_report(index, start, end, base_daily, mask, outcomes, pending, segment, name, output):
    months = [str(m) for m in pd.period_range(start,end,freq='M')]
    window_days = [str(d) for d in index if start<=str(d)<=end]
    selected_daily = mask.sum(axis=1)
    monthly = []
    for month in months:
        dates = [d for d in window_days if d.startswith(month)]
        selected = int(selected_daily.reindex(dates).sum())
        closed = [t for (day,code),t in outcomes.items() if day.startswith(month)]
        unresolved = sum(day.startswith(month) for day,code in pending)
        monthly.append({'segment':segment,'variant':name,'month':month,'market_sessions':len(dates),
            'original_opportunities':int(base_daily.reindex(dates).sum()),
            'original_signal_days':int(base_daily.reindex(dates).gt(0).sum()),
            'selected':selected,'selected_signal_days':int(selected_daily.reindex(dates).gt(0).sum()),
            'closed':len(closed),'unresolved':unresolved,'settled_net_sum':sum(t.net_return_pct for t in closed),
            'net_sum':None if unresolved else sum(t.net_return_pct for t in closed)})
    pd.DataFrame(monthly).to_csv(output/f'{segment}-{name}-monthly.csv',index=False)
    signal_days = int(selected_daily.gt(0).sum())
    original_days = int(base_daily.gt(0).sum())
    count = len(outcomes)
    return {'calendar_months':len(months),'market_sessions':len(window_days),
            'active_selected_months':sum(r['selected']>0 for r in monthly),
            'active_closed_months':sum(r['closed']>0 for r in monthly),
            'selected_signal_days':signal_days,'original_signal_days':original_days,
            'nonempty_original_day_coverage_pct':signal_days/original_days*100 if original_days else None,
            'closed_per_calendar_month':count/len(months),'selected_per_calendar_month':int(mask.to_numpy().sum())/len(months),
            'closed_per20_market_sessions':count/len(window_days)*20 if window_days else None,
            'selected_per20_market_sessions':int(mask.to_numpy().sum())/len(window_days)*20 if window_days else None,
            'max_month_closed':max(r['closed'] for r in monthly),
            'max_month_closed_share_pct':max(r['closed'] for r in monthly)/count*100 if count else None}


def evaluate(snapshot,live,segment,start,end,output):
    latest = next(r for r in reversed(live['runs']) if r.get('universe') and r['status']=='success')
    cfg = BacktestConfig(hold_days=3,stop_loss_pct=-7.,take_profit_pct=None,commission_bps=3,
                         stamp_duty_bps=5,slippage_bps=10,benchmark=None,strict_limit_prices=True,
                         economic_returns=True,valuation_end=end)
    engine = copy.copy(get('qianlong-close-v3'))
    engine.execution_adjust, engine.warmup_bars = 'none',300
    print('Prepare',segment,start,end,flush=True)
    with CutoffMarketStore(snapshot,end) as store:
        ctx = prepare_backtest_context(store,engine,start=start,end=end,params=latest['effective_params'],
                                       universe=latest['universe'],adjust='qfq',config=cfg,source_evidence_mode='compact')
        computed = engine.compute(ctx['panels'],ctx['resolved_params'])
        candidates = computed.factors['条件候选'] & computed.factors['弱市可交易']
        native = computed.factors['白线贴近度']
        gates, valid, features = structure_features(ctx['panels'])
        masks = {key:rank(candidates & gates[key],native,native) for key in VARIANTS}
        pd.testing.assert_frame_equal(masks['baseline'],computed.signals)
        pd.testing.assert_frame_equal(computed.signals.loc[start:end],ctx['signals'].loc[start:end].fillna(False).astype(bool))
        for mask in masks.values():assert mask.sum(axis=1).le(masks['baseline'].sum(axis=1)).all()
        midpoint = native.index[len(native)//2]
        prefix = {k:v.loc[:midpoint] if isinstance(v,pd.DataFrame) else v for k,v in ctx['panels'].items()}
        prefix_gates,prefix_valid,prefix_features = structure_features(prefix)
        for key in gates:
            pd.testing.assert_frame_equal(prefix_gates[key],gates[key].loc[:midpoint])
            pd.testing.assert_frame_equal(prefix_valid[key],valid[key].loc[:midpoint])
        for key in features:pd.testing.assert_frame_equal(prefix_features[key],features[key].loc[:midpoint])
        maturity = common_maturity_mask(native.index,start,end,max_hold=4)
        masks = {key:value.where(maturity,False,axis=0) for key,value in masks.items()}
        base_mask = masks['baseline']
        base_daily = base_mask.sum(axis=1)
        budget = int(base_daily.sum())
        original_rank = native.where(candidates).rank(axis=1,ascending=False,method='first')
        records = []
        for i,j in zip(*np.nonzero(candidates.where(maturity,False,axis=0).to_numpy())):
            item = {'signal_date':str(native.index[i]),'code':str(native.columns[j]),'native':float(native.iat[i,j]),
                    'original_rank':int(original_rank.iat[i,j]),'baseline_selected':bool(base_mask.iat[i,j]),
                    'name':ctx['resolved'].meta[native.columns[j]]['name'],'board':ctx['resolved'].meta[native.columns[j]]['board_bucket']}
            item.update({key:float(value.iat[i,j]) for key,value in features.items()})
            item.update({f'pass_{key}':bool(gates[key].iat[i,j]) for key in VARIANTS})
            item.update({f'known_{key}':bool(valid[key].iat[i,j]) for key in VARIANTS})
            records.append(item)
        pd.DataFrame(records).to_csv(output/f'{segment}-candidate-inputs.csv',index=False)
        runs,daily_frames,trade_groups,outcome_groups = {},{},{},{}
        base_keys = {(str(base_mask.index[i]),str(base_mask.columns[j])) for i,j in zip(*np.nonzero(base_mask.to_numpy()))}
        all_selected = []
        for name in VARIANTS:
            mask = masks[name]
            selected_keys = {(str(mask.index[i]),str(mask.columns[j])) for i,j in zip(*np.nonzero(mask.to_numpy()))}
            run = execute_split_context({**ctx,'signals':mask},cfg,start,end,max_hold=4)
            trades = run['closed_trades']
            trade_groups[name] = trades
            outcomes = {(t.signal_date,t.code):t for t in trades}
            outcome_groups[name] = outcomes
            pending = {(t.signal_date,t.code) for t in run['all_trades'] if t.exit_reason=='data_end'}
            trade_rows = [t.to_dict(include_factors=True) for t in run['all_trades']]
            pd.DataFrame(trade_rows,columns=list(trade_rows[0]) if trade_rows else
                         ['code','signal_date','entry_date','exit_date','gross_return_pct','net_return_pct','exit_reason']).to_csv(output/f'{segment}-{name}-trades.csv',index=False)
            added,removed,common = selected_keys-base_keys,base_keys-selected_keys,selected_keys & base_keys
            assert len(common)+len(removed)==budget and len(added)<=len(removed)
            for key in common & outcomes.keys() & outcome_groups['baseline'].keys():
                assert np.isclose(outcomes[key].net_return_pct,outcome_groups['baseline'][key].net_return_pct,atol=1e-10)
            added_trades = [outcomes[k] for k in added if k in outcomes]
            removed_trades = [outcome_groups['baseline'][k] for k in removed if k in outcome_groups['baseline']]
            add_sum = sum(t.net_return_pct for t in added_trades)
            remove_sum = sum(t.net_return_pct for t in removed_trades)
            base_sum = sum(t.net_return_pct for t in trade_groups['baseline'])
            assert np.isclose(sum(t.net_return_pct for t in trades)-base_sum,add_sum-remove_sum,atol=1e-9)
            daily = []
            for day in base_daily.index[base_daily>0]:
                unresolved = sum(d==day for d,c in pending)
                net = np.nan if unresolved else sum(t.net_return_pct for (d,c),t in outcomes.items() if d==day)
                daily.append({'segment':segment,'variant':name,'signal_date':day,'opportunities':int(base_daily.at[day]),
                              'selected':int(mask.loc[day].sum()),'unresolved':unresolved,'net_sum':net})
            daily = pd.DataFrame(daily)
            daily['delta_net_sum'] = daily.net_sum-daily_frames.get('baseline',daily).net_sum
            daily_frames[name] = daily
            daily.to_csv(output/f'{segment}-{name}-daily.csv',index=False)
            bundle = variant_bundle(trades,budget,len(pending))
            bundle['paired_month_block_bootstrap'] = paired_bootstrap(daily.dropna(subset=['delta_net_sum']))
            bundle['frequency'] = frequency_report(native.index,start,end,base_daily,mask,outcomes,pending,segment,name,output)
            bundle['accounting'] = {'selected':len(selected_keys),'closed':len(trades),'censored':len(pending),
                'execution_skipped':run['accounting']['skipped'],'coverage_pct':len(trades)/budget*100 if budget else None,
                'empty_original_days':int((base_daily.gt(0) & mask.sum(axis=1).eq(0)).sum()),
                'eligible_candidates':int((candidates & gates[name]).where(maturity,False,axis=0).sum().sum()),
                'unknown_candidates':int((candidates & ~valid[name]).where(maturity,False,axis=0).sum().sum()),
                'original_selected_with_unknown':int((base_mask & ~valid[name]).sum().sum())}
            assert len(trades)+len(pending)+sum(run['accounting']['skipped'].values())==len(selected_keys)
            bundle['attribution'] = {'added':len(added),'removed':len(removed),'common':len(common),
                'added_metrics':metrics(added_trades),'removed_metrics':metrics(removed_trades),
                'added_net_sum':add_sum,'removed_net_sum':remove_sum,
                'added_original_rank_counts':pd.Series([int(original_rank.at[d,c]) for d,c in added],dtype=int).value_counts().to_dict()}
            for day,code in sorted(selected_keys):
                trade = outcomes.get((day,code))
                all_selected.append({'segment':segment,'variant':name,'signal_date':day,'code':code,
                    'original_rank':int(original_rank.at[day,code]),'baseline_selected':(day,code) in base_keys,
                    'status':'closed' if trade else ('pending' if (day,code) in pending else 'execution_skipped'),
                    'net_return_pct':trade.net_return_pct if trade else (None if (day,code) in pending else 0)})
            if name in CONTROLS:
                old_selected = pd.read_csv(PARENT_STUDY/f'{segment}-selected.csv',dtype={'code':str})
                old_keys = {(str(r.signal_date),str(r.code)) for r in old_selected.itertuples() if r.variant==name}
                assert selected_keys==old_keys, (segment,name,'control selected keys')
                old_trades = pd.read_csv(PARENT_STUDY/f'{segment}-{name}-trades.csv',dtype={'code':str})
                old_values = {(str(r.signal_date),str(r.code)):float(r.net_return_pct) for r in old_trades.itertuples()}
                assert outcomes.keys()==old_values.keys()
                assert all(np.isclose(t.net_return_pct,old_values[k],atol=1e-10) for k,t in outcomes.items())
                bundle['parent_control_reproduced'] = True
            runs[name] = bundle
            print(segment,name,json.dumps({'metrics':bundle['metrics'],'opportunity_mean':bundle['original_opportunity_mean'],
                'coverage':bundle['accounting']['coverage_pct'],'added':len(added),'unknown':bundle['accounting']['unknown_candidates'],'frequency':bundle['frequency']},ensure_ascii=False),flush=True)
        pd.DataFrame(all_selected).to_csv(output/f'{segment}-selected.csv',index=False)
        result = {'context':{'start':start,'end':end,'columns':len(native.columns),'warmup':300,'min_bars_unchanged':engine.min_bars(),
                   'original_opportunities':budget,'mature_candidates':len(records),'baseline_reproduced':True,'prefix_causality_equal':True,
                   'tail_original_purged':int(computed.signals.loc[start:end].sum().sum())-budget},'runs':runs}
        if segment=='observed_2026h2':
            for size in (20,60):
                recent_start = str(native.index[-size])
                recent = {'start':recent_start,'end':end,'runs':{}}
                for name in VARIANTS:
                    trades = [t for t in trade_groups[name] if t.signal_date>=recent_start]
                    daily = daily_frames[name].query('signal_date>=@recent_start')
                    recent['runs'][name] = variant_bundle(trades,int(daily.opportunities.sum()),int(daily.unresolved.sum()))
                result[f'last{size}_sessions'] = recent
        write_json(output/f'{segment}-summary.json',result)
    gc.collect()
    return result


def training_nominees(result):
    base = result['runs']['baseline']
    replacement,quality = [],[]
    for name,run in result['runs'].items():
        if name in CONTROLS or run['unresolved']:continue
        m,b,f = run['metrics'],base['metrics'],run['frequency']
        if (m['trades']>=40 and m['win_rate']>=55 and m['win_rate']>b['win_rate']
                and m['avg_net_return']>=1 and m['avg_net_return']>b['avg_net_return']
                and (m['profit_factor'] or 0)>max(1.3,b['profit_factor'] or 0)
                and 2*f['active_selected_months']>=f['calendar_months']
                and run['double_cost']['avg_net_return']>0 and run['largest_winner_removed']['avg_net_return']>0):
            quality.append(name)
            if m['trades']>=80 and run['original_opportunity_mean']>base['original_opportunity_mean']:
                replacement.append(name)
    order = lambda n:(-result['runs'][n]['original_opportunity_mean'],-result['runs'][n]['metrics']['win_rate'],n)
    replacement.sort(key=order)
    quality.sort(key=order)
    return {'replacement':replacement[:2],'frequency_quality_subset':quality[:2]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--context',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    out = args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if (out/'PLAN.json').exists():raise FileExistsError('Preserve frozen studies')
    live = json.loads(args.context.read_text(encoding='utf-8'))
    data_hash,before = sha256(args.snapshot),source_hashes()
    assert data_hash==live['snapshot_sha256']
    assert before['src/strategy/application/qianlong.py']==live['source_hashes']['src/strategy/application/qianlong.py']
    formulas = {
        'long_bull':'CONTROL C>MA60>MA120, MA60>lag20, MA120>=lag20',
        'low_range_bull':'CONTROL long_bull and 0<=Pos120_T<=.4; prior120 high/low excludingT',
        'prior20_lower':'long_bull and 0<=Pos20_pre<=.5; prior20 high/low and C_T-1',
        'prior60_lower':'long_bull and 0<=Pos60_pre<=.5; prior60 high/low and C_T-1',
        'support_retest':'long_bull and prior10 each low/MA60>=.98, at leastonce<=1.03; no volume condition',
        'near_ma60':'long_bull and C<=1.08*MA60; not full short-MA stack, not max-loss guarantee',
        'base_repair':'C>MA20>MA60,MA20>lag5,MA60>lag20,MA120>=.99*lag20,C<=1.10*MA120,0<=Pos120_T<=.6; no recent cross prerequisite',
        'rising_floor':'long_bull and lowmin_T-5..T-1 >=1.01*lowmin_T-10..T-6,C<=1.05*MA20; equal disjoint windows, not confirmed pivots',
    }
    parent_hashes = {p.name:sha256(p) for p in PARENT_STUDY.iterdir() if p.suffix in ('.csv','.json') and p.name!='verification.json'}
    plan = {'created_at':now(),'snapshot_sha256':data_hash,'source_hashes':before,'splits':SPLITS,'variants':VARIANTS,
        'formulas':formulas,'parent_artifact_hashes':parent_hashes,'warmup':300,'baseline_min_bars':46,'ranking':'Full original eligible universe; filter then native Top2; no fill if fewer than2; execution cancellations no refills.',
        'missing':'Per-variant required history missing => unknown, excluded only from that structure; original candidates/breadth/baseline retained.',
        'exit':{'entry':'next_open','hold_days_after_entry':3,'stop_loss_pct':-7,'cost_pct':.31,'stress_cost_pct':.62},
        'selection':'Train-only new definitions. Frequency-quality: >=40 closed, win>=55% and >baseline, mean>=1% and >baseline, PF>max(1.3,baseline), active selected months>=half calendar months including zeros, doublecost mean>0, largestwinnerremoved mean>0. Replacement additionally>=80 closed and original opportunity mean>baseline. Top2 by opportunity mean/win/id. No later tuning; all9 arms reported; controls cannot be new nominees.',
        'budget':'Original Top2 maturity budget fixed. Structure filters may refill from rank3plus; added<=removed; report both subset quality and original opportunity return.',
        'frequency':'Calendar months include zeros; partial months identified by market sessions. Also report events per20 market sessions and nonempty original signal-day coverage.',
        'limitations':['All periods already observed; repeated search and retrospective selection, not fresh OOS.',
            'Current directory/ST/state/revised factors have historical/PIT/survivor bias.',
            '300 bars loading cannot create absent pre2023 or new-stock history; record unknown.',
            'Long trend is a selection context; fixed 3-day exits do not test long-term holding.',
            'Independent event returns not portfolio NAV/capacity; daily strict exits and costs remain assumptions.']}
    write_json(out/'PLAN.json',plan)
    write_json(out/'freeze-receipt.json',{'created_at':now(),'plan_sha256':sha256(out/'PLAN.json')})
    summary = {'segments':{},'training_nominees':None,'plan_sha256':sha256(out/'PLAN.json')}
    for segment,(start,end) in SPLITS.items():
        assert source_hashes()==before
        result = evaluate(args.snapshot,live,segment,start,end,out)
        summary['segments'][segment] = result
        if segment=='train':
            summary['training_nominees'] = training_nominees(result)
            write_json(out/'training-nomination.json',{'created_at':now(),'nominees':summary['training_nominees'],
                'train_summary_sha256':sha256(out/'train-summary.json'),'plan_sha256':summary['plan_sha256']})
        write_json(out/'summary.json',summary)
    assert source_hashes()==before and sha256(args.snapshot)==data_hash
    assert {p.name:sha256(p) for p in PARENT_STUDY.iterdir() if p.name in parent_hashes}==parent_hashes
    write_json(out/'completion-receipt.json',{'completed_at':now(),'snapshot_sha256':data_hash,'source_hashes':before,
        'plan_sha256':summary['plan_sha256'],'summary_sha256':sha256(out/'summary.json')})
    print('Completed',str(out),summary['training_nominees'],flush=True)


if __name__=='__main__':
    main()
