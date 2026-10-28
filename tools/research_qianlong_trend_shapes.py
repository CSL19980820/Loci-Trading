"""Frozen Qianlong + long-trend shape filters on a read-only snapshot.

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

VARIANTS = ('baseline','long_bull','annual_bull','low_range_bull',
            'quiet_pullback','early_repair','low_extension_bull')


def structure_features(panels):
    close, high, low, volume = (panels[k] for k in ('close','high','low','volume'))
    ma = {n:close.rolling(n).mean() for n in (5,10,20,60,120,250)}
    lo120 = low.where(low.gt(0) & np.isfinite(low)).shift(1).rolling(120).min()
    hi120 = high.where(high.gt(0) & np.isfinite(high)).shift(1).rolling(120).max()
    pos120 = (close-lo120)/(hi120-lo120).where(hi120.gt(lo120))
    ratio60 = (low/ma[60]).where(low.gt(0) & np.isfinite(low)).shift(1)
    pullback_min, pullback_max = ratio60.rolling(10).min(), ratio60.rolling(10).max()
    past_volume = volume.where(volume.gt(0) & np.isfinite(volume)).shift(1)
    vol5, vol20 = past_volume.rolling(5).mean(), past_volume.rolling(20).mean()
    cross20_60 = ma[20].gt(ma[60]) & ma[20].shift(1).le(ma[60].shift(1))
    recent_cross = cross20_60.astype(float).rolling(20).sum().gt(0)
    valid_base = np.isfinite(close) & close.gt(0) & np.isfinite(ma[60]) & np.isfinite(ma[60].shift(20))
    valid_base &= np.isfinite(ma[120]) & np.isfinite(ma[120].shift(20))
    valid_annual = valid_base & np.isfinite(ma[250]) & np.isfinite(ma[250].shift(20))
    valid_position = valid_base & np.isfinite(pos120)
    valid_pullback = valid_base & np.isfinite(pullback_min) & np.isfinite(pullback_max)
    valid_pullback &= np.isfinite(vol5) & np.isfinite(vol20) & vol20.gt(0)
    valid_repair = valid_position & np.isfinite(ma[20]) & np.isfinite(ma[20].shift(5))
    valid_full = valid_base & np.isfinite(ma[5]) & np.isfinite(ma[10]) & np.isfinite(ma[20])
    g1 = close.gt(ma[60]) & ma[60].gt(ma[120]) & ma[60].gt(ma[60].shift(20)) & ma[120].ge(ma[120].shift(20))
    conditions = {
        'baseline':pd.DataFrame(True,index=close.index,columns=close.columns),
        'long_bull':g1,
        'annual_bull':g1 & ma[120].gt(ma[250]) & ma[120].gt(ma[120].shift(20)) & ma[250].ge(ma[250].shift(20)),
        'low_range_bull':g1 & pos120.ge(0) & pos120.le(.4),
        'quiet_pullback':g1 & pullback_min.ge(.98) & pullback_min.le(1.03) & vol5.le(.8*vol20),
        'early_repair':close.gt(ma[20]) & ma[20].gt(ma[60]) & close.gt(ma[120]) & ma[20].gt(ma[20].shift(5))
            & ma[60].ge(ma[60].shift(20)) & ma[120].ge(ma[120].shift(20)) & recent_cross & pos120.ge(0) & pos120.le(.6),
        'low_extension_bull':g1 & close.gt(ma[5]) & ma[5].gt(ma[10]) & ma[10].gt(ma[20]) & ma[20].gt(ma[60]) & close.le(1.05*ma[20]),
    }
    valid = {'baseline':conditions['baseline'],'long_bull':valid_base,'annual_bull':valid_annual,
             'low_range_bull':valid_position,'quiet_pullback':valid_pullback,
             'early_repair':valid_repair,'low_extension_bull':valid_full}
    gates = {key:(value & valid[key]).fillna(False) for key,value in conditions.items()}
    features = {f'ma{n}':value for n,value in ma.items()}
    features.update({'ma60_lag20':ma[60].shift(20),'ma120_lag20':ma[120].shift(20),'ma250_lag20':ma[250].shift(20),
                     'ma20_lag5':ma[20].shift(5),'position120':pos120,'prior_low120':lo120,'prior_high120':hi120,
                     'past10_min_low_ma60':pullback_min,'past10_max_low_ma60':pullback_max,
                     'past5_volume':vol5,'past20_volume':vol20,'recent_cross20_60':recent_cross.astype(float),
                     'close':close})
    return gates, valid, features


def source_hashes():
    paths = ['tools/research_qianlong_trend_shapes.py','tools/research_qianlong_optimization.py',
             'tools/research_qianlong_recent.py','tools/research_chinext_payoff_exits.py',
             'tools/research_impulse_scoring.py','src/strategy/application/qianlong.py',
             'src/backtest/application/runner.py','src/backtest/application/engine.py',
             'src/market/infrastructure/store_panel.py']
    return {p:sha256(ROOT/p) for p in paths}


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
            runs[name] = bundle
            print(segment,name,json.dumps({'metrics':bundle['metrics'],'opportunity_mean':bundle['original_opportunity_mean'],
                'coverage':bundle['accounting']['coverage_pct'],'added':len(added),'unknown':bundle['accounting']['unknown_candidates']},ensure_ascii=False),flush=True)
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
        if name=='baseline' or run['unresolved']:continue
        m,b = run['metrics'],base['metrics']
        if (m['trades']>=40 and m['win_rate']>b['win_rate'] and m['avg_net_return']>b['avg_net_return']
                and (m['profit_factor'] or 0)>max(1,b['profit_factor'] or 0)
                and run['double_cost']['avg_net_return']>0 and run['largest_winner_removed']['avg_net_return']>0):
            quality.append(name)
            if m['trades']>=80 and run['original_opportunity_mean']>base['original_opportunity_mean']:
                replacement.append(name)
    replacement.sort(key=lambda n:(-result['runs'][n]['original_opportunity_mean'],n))
    quality.sort(key=lambda n:(-result['runs'][n]['metrics']['avg_net_return'],-result['runs'][n]['metrics']['win_rate'],n))
    return {'replacement':replacement[:2],'quality_subset':quality[:2]}


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
    formulas = {'long_bull':'C>MA60>MA120, MA60>MA60_T-20, MA120>=MA120_T-20',
        'annual_bull':'long_bull and MA120>MA250, MA120>MA120_T-20, MA250>=MA250_T-20',
        'low_range_bull':'long_bull and 0<=Pos120<=.4; Pos uses C_T and prior120 high/low excludingT',
        'quiet_pullback':'long_bull and prior10 each low/MA60>=.98, at leastonce<=1.03; prior5 meanvolume<=.8*prior20 meanvolume',
        'early_repair':'C>MA20>MA60,C>MA120,MA20>lag5,MA60/120>=lag20,MA20 crossedaboveMA60 inlast20,0<=Pos120<=.6',
        'low_extension_bull':'long_bull and C>MA5>MA10>MA20>MA60>MA120,C<=1.05*MA20'}
    plan = {'created_at':now(),'snapshot_sha256':data_hash,'source_hashes':before,'splits':SPLITS,'variants':VARIANTS,
        'formulas':formulas,'warmup':300,'baseline_min_bars':46,'ranking':'Full original eligible universe; filter then native Top2; no fill if fewer than2; execution cancellations no refills.',
        'missing':'Per-variant required history missing => unknown, excluded only from that structure; original candidates/breadth/baseline retained.',
        'exit':{'entry':'next_open','hold_days_after_entry':3,'stop_loss_pct':-7,'cost_pct':.31,'stress_cost_pct':.62},
        'selection':'Train-only. Quality subset: >=40 closed, win/mean/PF>baseline and PF>1, doublecost mean>0, largestwinnerremoved mean>0; top2 by mean/win/id. Replacement additionally>=80 closed and original opportunity mean>baseline; top2 by opportunity mean/id. No later tuning; all7 arms reported.',
        'budget':'Original Top2 maturity budget fixed. Structure filters may refill from rank3plus; added<=removed; report both subset quality and original opportunity return.',
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
    write_json(out/'completion-receipt.json',{'completed_at':now(),'snapshot_sha256':data_hash,'source_hashes':before,
        'plan_sha256':summary['plan_sha256'],'summary_sha256':sha256(out/'summary.json')})
    print('Completed',str(out),summary['training_nominees'],flush=True)


if __name__=='__main__':
    main()
