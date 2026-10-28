"""Frozen, read-only Qianlong trend/support/open-price experiment.

Run via tools/isolated_check.py. Writes only the requested research directory.
No changes to registered strategies, source databases, scheduler or accounts.
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
from tools.research_qianlong_recent import metrics  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

SPLITS = {
    'train': ('2024-01-01', '2025-06-30'),
    'validation_2025h2': ('2025-07-01', '2025-12-31'),
    'observed_2026h1': ('2026-01-01', '2026-06-30'),
    'observed_2026h2': ('2026-07-01', '2026-10-09'),
}
VARIANTS = {
    'baseline': ('baseline', 'none'),
    'trend': ('trend', 'none'),
    'support': ('support', 'none'),
    'combined': ('combined', 'none'),
    'baseline_price': ('baseline', 'price'),
    'combined_price': ('combined', 'price'),
    'baseline_structure': ('baseline', 'structure'),
    'combined_structure': ('combined', 'structure'),
}


def score_features(panels, white):
    """T-day scores; complete history only, explicit neutral unknown features."""
    close, low = panels['close'], panels['low']
    ma20, ma60 = close.rolling(20).mean(), close.rolling(60).mean()
    r_known = np.isfinite(close) & np.isfinite(ma20) & np.isfinite(ma20.shift(10))
    r_true = close.gt(ma20) & ma20.gt(ma20.shift(10))
    repair = r_true.astype(float).where(r_known, .5)
    u_known = r_known & (~r_true | (np.isfinite(ma60) & np.isfinite(ma60.shift(10))))
    u_true = r_true & ma20.ge(ma60) & ma60.ge(ma60.shift(10))
    uptrend = u_true.astype(float).where(u_known, .5)
    floor = low.where(low.gt(0) & np.isfinite(low)).shift(1).rolling(5).min()
    p_known = np.isfinite(floor) & floor.gt(0) & np.isfinite(close) & close.gt(0)
    distance = (close-floor)/close
    support_quality = (1-distance/.07).clip(0, 1).where(floor.lt(close), 0).where(p_known, .5)
    native = (100*white/close).clip(0, 100)
    trend_penalty = 2*(1-repair)+(1-uptrend)
    support_penalty = 3*(1-support_quality)
    scores = {'baseline':native,'trend':(native-trend_penalty).clip(0, 100),
              'support':(native-support_penalty).clip(0, 100),
              'combined':(native-.5*trend_penalty-.5*support_penalty).clip(0, 100)}
    features = {'repair':repair,'uptrend':uptrend,'floor':floor,'support_quality':support_quality,
                'trend_penalty':trend_penalty,'support_penalty':support_penalty,
                'trend_unknown':~(r_known & u_known),'support_unknown':~p_known}
    return scores, features


def rank(candidates, score, native):
    """No quantization: descending score, native closeness, ascending code."""
    mask = pd.DataFrame(False,index=score.index,columns=score.columns)
    for day in score.index:
        codes = list(score.columns[candidates.loc[day]])
        ordered = sorted(codes,key=lambda c:(-score.at[day,c],-native.at[day,c],str(c)))
        mask.loc[day,ordered[:2]] = True
    return mask


def opening_acceptance(signal_panels, execution_panels, white, floor):
    """Decision uses E open and factors, T close/support; never E HLC/volume."""
    raw_close = execution_panels['close']
    factors = execution_panels['__adjust_factor']
    open_in_t = execution_panels['open'].shift(-1)*factors.shift(-1)/factors
    white_raw_t = white/signal_panels['close']*raw_close
    floor_raw_t = floor/signal_panels['close']*raw_close
    gap_pct = (open_in_t/raw_close-1)*100
    known = np.isfinite(open_in_t) & open_in_t.gt(0) & np.isfinite(raw_close) & raw_close.gt(0)
    known &= np.isfinite(factors) & factors.gt(0) & np.isfinite(factors.shift(-1)) & factors.shift(-1).gt(0)
    price_known = known & np.isfinite(white_raw_t) & white_raw_t.gt(0)
    structural_known = known & np.isfinite(floor_raw_t) & floor_raw_t.gt(0)
    price_ok = price_known & gap_pct.le(2) & open_in_t.ge(white_raw_t)
    structure_ok = structural_known & open_in_t.gt(floor_raw_t) & open_in_t.le(floor_raw_t/.93)
    gates = {'none':pd.DataFrame(True,index=raw_close.index,columns=raw_close.columns),
             'price':price_ok.fillna(False),'structure':structure_ok.fillna(False)}
    details = {'entry_open_in_t':open_in_t,'entry_gap_pct':gap_pct,'white_raw_t':white_raw_t,
               'floor_raw_t':floor_raw_t,'price_unknown':~price_known,'structure_unknown':~structural_known,
               'gap_above_2':gap_pct.gt(2),'below_white':open_in_t.lt(white_raw_t),
               'below_floor':open_in_t.le(floor_raw_t),
               'structure_risk_over_7':open_in_t.gt(floor_raw_t/.93)}
    return gates, details


def variant_bundle(trades, budget, censor_count):
    best = max(trades,key=lambda t:t.net_return_pct) if trades else None
    reduced = [t for t in trades if t is not best]
    total = sum(t.net_return_pct for t in trades)
    return {'metrics':metrics(trades), 'original_opportunity_mean':total/budget if budget and not censor_count else None,
            'settled_net_sum':total,'original_opportunities':budget,'unresolved':censor_count,
            'double_cost':metrics(trades,.62),
            'double_cost_opportunity_mean':sum(t.gross_return_pct-.62 for t in trades)/budget if budget and not censor_count else None,
            'largest_winner_removed':metrics(reduced),
            'largest_winner_removed_opportunity_mean':sum(t.net_return_pct for t in reduced)/budget if budget and not censor_count else None,
            'double_cost_largest_winner_removed_opportunity_mean':sum(t.gross_return_pct-.62 for t in reduced)/budget if budget and not censor_count else None}


def evaluate(snapshot, live, segment, start, end, output):
    latest = next(r for r in reversed(live['runs']) if r.get('universe') and r['status']=='success')
    params, universe = latest['effective_params'], latest['universe']
    cfg = BacktestConfig(hold_days=3,stop_loss_pct=-7.,take_profit_pct=None,
                         commission_bps=3,stamp_duty_bps=5,slippage_bps=10,benchmark=None,
                         strict_limit_prices=True,economic_returns=True,valuation_end=end)
    engine = copy.copy(get('qianlong-close-v3'))
    engine.execution_adjust, engine.warmup_bars = 'none', 160
    print('Prepare',segment,start,end,flush=True)
    with CutoffMarketStore(snapshot,end) as store:
        ctx = prepare_backtest_context(store,engine,start=start,end=end,params=params,universe=universe,
                                       adjust='qfq',config=cfg,source_evidence_mode='compact')
        computed = engine.compute(ctx['panels'],params)
        factors, panels = computed.factors, ctx['panels']
        candidates = factors['条件候选'] & factors['弱市可交易']
        white = factors['辰星线']
        scores, features = score_features(panels,white)
        masks = {key:rank(candidates,score,scores['baseline']) for key,score in scores.items()}
        pd.testing.assert_frame_equal(masks['baseline'],computed.signals)
        pd.testing.assert_frame_equal(computed.signals.loc[start:end],ctx['signals'].loc[start:end].fillna(False).astype(bool))
        for mask in masks.values():
            pd.testing.assert_series_equal(mask.sum(axis=1),masks['baseline'].sum(axis=1))
        midpoint = panels['close'].index[len(panels['close'])//2]
        prefix = {k:v.loc[:midpoint] if isinstance(v,pd.DataFrame) else v for k,v in panels.items()}
        prefix_scores,prefix_features = score_features(prefix,white.loc[:midpoint])
        for key in scores:pd.testing.assert_frame_equal(prefix_scores[key],scores[key].loc[:midpoint])
        for key in features:pd.testing.assert_frame_equal(prefix_features[key],features[key].loc[:midpoint])
        gates, opening = opening_acceptance(panels,ctx['execution_panels'],white,features['floor'])
        maturity = common_maturity_mask(white.index,start,end,max_hold=4)
        base_mask = masks['baseline'].where(maturity,False,axis=0)
        original_daily = base_mask.sum(axis=1)
        budget = int(original_daily.sum())
        source_rows = []
        for i,j in zip(*np.nonzero(candidates.where(maturity,False,axis=0).to_numpy())):
            day,code = str(white.index[i]),str(white.columns[j])
            item = {'signal_date':day,'code':code,'name':ctx['resolved'].meta[code]['name'],
                    'board':ctx['resolved'].meta[code]['board_bucket']}
            item.update({key:float(value.iat[i,j]) for key,value in scores.items()})
            item.update({key:float(value.iat[i,j]) for key,value in features.items()})
            item.update({key:float(value.iat[i,j]) for key,value in opening.items()})
            source_rows.append(item)
        pd.DataFrame(source_rows).to_csv(output/f'{segment}-candidate-inputs.csv',index=False)
        runs, daily_by_variant, closed_by_variant = {}, {}, {}
        all_decisions = []
        for name,(score_key,entry_key) in VARIANTS.items():
            nominated = masks[score_key].where(maturity,False,axis=0)
            accepted = nominated & gates[entry_key]
            run = execute_split_context({**ctx,'signals':accepted},cfg,start,end,max_hold=4)
            trades = run['closed_trades']
            closed_by_variant[name] = trades
            closed = {(t.signal_date,t.code):t for t in trades}
            unresolved = {(t.signal_date,t.code) for t in run['all_trades'] if t.exit_reason=='data_end'}
            trade_rows = [t.to_dict(include_factors=True) for t in run['all_trades']]
            pd.DataFrame(trade_rows,columns=list(trade_rows[0]) if trade_rows else
                         ['code','signal_date','entry_date','exit_date','gross_return_pct','net_return_pct','exit_reason']).to_csv(output/f'{segment}-{name}-trades.csv',index=False)
            daily = []
            for day in original_daily.index[original_daily>0]:
                censored = any(d==day for d,c in unresolved)
                daily.append({'segment':segment,'variant':name,'signal_date':day,
                    'opportunities':int(original_daily.at[day]),'nominated':int(nominated.loc[day].sum()),
                    'accepted':int(accepted.loc[day].sum()),'unresolved':int(censored),
                    'net_sum':np.nan if censored else sum(t.net_return_pct for (d,c),t in closed.items() if d==day)})
            daily = pd.DataFrame(daily)
            daily_by_variant[name] = daily
            bundle = variant_bundle(trades,budget,len(unresolved))
            bundle['accounting'] = {'nominated':int(nominated.sum().sum()),'accepted':int(accepted.sum().sum()),
                 'price_rejected':int((nominated & ~gates[entry_key]).sum().sum()),
                 'closed':len(trades),'censored':len(unresolved),'execution_skipped':run['accounting']['skipped'],
                 'coverage_pct':len(trades)/budget*100 if budget else None,
                 'unknown_feature_nominations':int((nominated & (features['trend_unknown']|features['support_unknown'])).sum().sum())}
            assert bundle['accounting']['nominated']==budget
            assert bundle['accounting']['accepted']+bundle['accounting']['price_rejected']==budget
            assert len(trades)+len(unresolved)+sum(run['accounting']['skipped'].values())==bundle['accounting']['accepted']
            for i,j in zip(*np.nonzero(nominated.to_numpy())):
                day,code = str(nominated.index[i]),str(nominated.columns[j])
                key = day,code
                status = 'rejected' if not accepted.iat[i,j] else ('closed' if key in closed else ('pending' if key in unresolved else 'execution_skipped'))
                item = {'segment':segment,'variant':name,'signal_date':day,'code':code,
                        'score':float(scores[score_key].iat[i,j]),'accepted':bool(accepted.iat[i,j]),'status':status,
                        'net_return_pct':closed[key].net_return_pct if key in closed else (None if key in unresolved else 0),
                        'baseline_selected':bool(base_mask.iat[i,j])}
                item.update({key:float(value.iat[i,j]) for key,value in opening.items()})
                all_decisions.append(item)
            base = daily_by_variant['baseline']
            paired = daily.merge(base[['signal_date','net_sum']],on='signal_date',suffixes=('','_baseline'),validate='one_to_one')
            paired = paired.dropna(subset=['net_sum','net_sum_baseline'])
            paired['delta_net_sum'] = paired.net_sum-paired.net_sum_baseline
            bundle['paired_month_block_bootstrap'] = paired_bootstrap(paired)
            daily['delta_net_sum'] = daily.net_sum-base.net_sum
            daily.to_csv(output/f'{segment}-{name}-daily.csv',index=False)
            runs[name] = bundle
            print(segment,name,json.dumps({'metrics':bundle['metrics'],'opportunity_mean':bundle['original_opportunity_mean'],
                'accepted':bundle['accounting']['accepted'],'budget':budget},ensure_ascii=False),flush=True)
        decisions = pd.DataFrame(all_decisions)
        decisions.to_csv(output/f'{segment}-decisions.csv',index=False)
        unknown = candidates & (features['trend_unknown']|features['support_unknown'])
        result = {'start':start,'end':end,'runs':runs,'context':{'revision':engine.strategy_revision,
                  'universe':universe,'params':params,'columns':len(white.columns),'baseline_reproduced':True,
                  'prefix_causality_equal':True,'original_opportunities':budget,
                  'mature_candidate_count':int(candidates.where(maturity,False,axis=0).sum().sum()),
                  'unknown_context_candidates':int(unknown.where(maturity,False,axis=0).sum().sum()),
                  'tail_original_signals_purged':int(masks['baseline'].loc[start:end].sum().sum())-budget}}
        if segment=='observed_2026h2':
            for size in (20,60):
                recent_start = str(white.index[-size])
                result[f'last{size}_sessions'] = {'start':recent_start,'end':end,'runs':{}}
                for name in VARIANTS:
                    selected_trades = [t for t in closed_by_variant[name] if t.signal_date>=recent_start]
                    d = daily_by_variant[name].query('signal_date>=@recent_start')
                    result[f'last{size}_sessions']['runs'][name] = variant_bundle(selected_trades,int(d.opportunities.sum()),int(d.unresolved.sum()))
        for name in VARIANTS:
            for trade in closed_by_variant[name]:
                original = next((t for t in closed_by_variant['baseline'] if t.signal_date==trade.signal_date and t.code==trade.code),None)
                if original:assert np.isclose(original.net_return_pct,trade.net_return_pct,atol=1e-10)
        write_json(output/f'{segment}-summary.json',result)
    gc.collect()
    return result


def nominate(result):
    base = result['runs']['baseline']
    b = base['metrics']
    eligible = []
    for name,run in result['runs'].items():
        m = run['metrics']
        if (name!='baseline' and m['trades']>=80 and run['accounting']['coverage_pct']>=50 and not run['unresolved']
                and m['win_rate']>b['win_rate'] and m['avg_net_return']>b['avg_net_return']
                and run['original_opportunity_mean']>base['original_opportunity_mean']
                and (m['profit_factor'] or 0)>max(1,b['profit_factor'] or 0)):
            eligible.append(name)
    return sorted(eligible,key=lambda name:(-result['runs'][name]['original_opportunity_mean'],
                                           -result['runs'][name]['metrics']['profit_factor'],name))[:3]


def source_hashes():
    paths = ['tools/research_qianlong_optimization.py','tools/research_qianlong_recent.py',
             'tools/research_chinext_payoff_exits.py','tools/research_impulse_scoring.py',
             'src/strategy/application/qianlong.py','src/backtest/application/engine.py',
             'src/backtest/application/runner.py','src/market/infrastructure/store_panel.py']
    return {p:sha256(ROOT/p) for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--context',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True,exist_ok=True)
    if (out/'PLAN.json').exists():raise FileExistsError('Do not overwrite frozen research')
    live = json.loads(args.context.read_text(encoding='utf-8'))
    snapshot_hash = sha256(args.snapshot)
    assert snapshot_hash==live['snapshot_sha256']
    before = source_hashes()
    assert before['src/strategy/application/qianlong.py']==live['source_hashes']['src/strategy/application/qianlong.py']
    plan = {'created_at':now(),'snapshot_sha256':snapshot_hash,'source_hashes':before,'splits':SPLITS,
            'variants':VARIANTS,'score_formulas':{'S':'100*white_T/close_T','R':'C>MA20 and MA20>MA20_T-10',
                'U':'R and MA20>=MA60 and MA60>=MA60_T-10','P':'minimum valid LOW from T-5 through T-1',
                'Z':'clip(1-((C-P)/C)/.07,0,1); P>=C => 0',
                'trend':'S-2*(1-R)-(1-U)','support':'S-3*(1-Z)',
                'combined':'S-(1-R)-.5*(1-U)-1.5*(1-Z)','unknown':'unknown R/U/Z=.5, no missing-price interpolation'},
            'entry_formulas':{'none':'original next_open','price':'economic gap<=2% AND next_open>=T white',
                'structure':'P<economic next_open<=P/.93','causality':'T ranks frozen before next_open; no refills, E HLCV not decision features'},
            'exit':{'hold_days_after_entry':3,'stop_loss_pct':-7,'take_profit_pct':None,'cost_pct':.31,'stress_cost_pct':.62},
            'selection':'Train-only: >=80 closed and >=50% original coverage, win rate/mean/opportunity mean/PF exceed baseline, PF>1; at most3 by opportunity mean/PF/id. No later tuning. All8 fixed arms reported in every period.',
            'budget':'Same T-day Top2 count. Rejected or execution-cancelled opportunities zero; unresolved labels unknown, never zero.',
            'limitations':['All splits previously observed and retrospective; no fresh OOS claim.',
                           'Current universe metadata/ST/names and revised factors, survivor/PIT bias.',
                           'Conditional same-open fills are optimistic opening proxies, not proven auction execution.',
                           'Independent events rather than portfolio NAV/capacity; strict daily limit-down exits conservative.',
                           'Seven fixed alternatives and prior studies entail multiple testing; descriptive CI not corrected.']}
    write_json(out/'PLAN.json',plan)
    write_json(out/'freeze-receipt.json',{'created_at':now(),'plan_sha256':sha256(out/'PLAN.json')})
    summary = {'segments':{},'training_nominees':None,'plan_sha256':sha256(out/'PLAN.json')}
    for segment,(start,end) in SPLITS.items():
        assert source_hashes()==before
        result = evaluate(args.snapshot,live,segment,start,end,out)
        summary['segments'][segment] = result
        if segment=='train':
            summary['training_nominees'] = nominate(result)
            write_json(out/'training-nomination.json',{'created_at':now(),'nominees':summary['training_nominees'],
                'train_summary_sha256':sha256(out/'train-summary.json'),'plan_sha256':summary['plan_sha256']})
        write_json(out/'summary.json',summary)
    assert source_hashes()==before
    assert sha256(args.snapshot)==snapshot_hash
    write_json(out/'completion-receipt.json',{'completed_at':now(),'source_hashes':before,'snapshot_sha256':snapshot_hash,
        'plan_sha256':summary['plan_sha256'],'summary_sha256':sha256(out/'summary.json')})
    print('Completed',str(out),'nominees',summary['training_nominees'],flush=True)


if __name__=='__main__':
    main()
