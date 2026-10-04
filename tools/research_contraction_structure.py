"""A new causal push/consolidation/first-breakout research family; offline only.

The density phase reads training signals, never forward returns. All shapes,
execution guards, exits and nomination rules must be frozen before performance.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from src.backtest.application.engine import _resolve_exit, run_backtest  # noqa: E402
from src.backtest.application.execution_contract import strict_price_masks  # noqa: E402
from src.backtest.application.runner import prepare_backtest_context  # noqa: E402
from src.backtest.domain.models import Trade  # noqa: E402
from src.strategy.application.catalog import get  # noqa: E402
from tools.research_chinext_payoff_exits import (  # noqa: E402
    BASELINE,
    CutoffMarketStore,
    common_maturity_mask,
    context_evidence,
    sha256,
    source_hashes,
)
from tools.research_chinext_payoff_filters import (  # noqa: E402
    SPLITS,
    independent_metrics,
)
from tools.research_impulse_scoring import now, paired_bootstrap  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

SLUG="contraction-rebreakout-v1"
OUTPUT=ROOT/"docs/research/2026-10-04-contraction-structure"
SHAPES={
    "compact3":dict(push=5,pause=3,min_push_pct=8.,max_width_pct=8.,max_tr_ratio=.75,max_volume_ratio=.80,lifetime=5),
    "shelf5":dict(push=10,pause=5,min_push_pct=10.,max_width_pct=10.,max_tr_ratio=.70,max_volume_ratio=.75,lifetime=7),
    "base8":dict(push=15,pause=8,min_push_pct=12.,max_width_pct=12.,max_tr_ratio=.70,max_volume_ratio=.70,lifetime=10),
}
CONTROLS=("legacy_original4","baseline_flat4")
VARIANTS={**{key:dict(family="original",exit="fixed4",deduplicate=key=="baseline_flat4") for key in CONTROLS},
    **{f"{family}_{mode}":dict(family=family,exit=mode,deduplicate=True) for family in SHAPES for mode in ("fixed4","structure10")}}
COMMON_MATURITY=20


def sources():
    paths=["tools/research_contraction_structure.py","tools/research_chinext_payoff_filters.py","tools/research_impulse_scoring.py"]
    return {**source_hashes(),**{p:sha256(ROOT/p) for p in paths}}


def prepare(db:Path,start:str,end:str):
    store=CutoffMarketStore(db,end)
    try:
        engine=copy.copy(get(SLUG))
        engine.requires_full_history=True
        ctx=prepare_backtest_context(store,engine,start=start,end=end,config=BASELINE.config(end),source_evidence_mode="compact")
        computed=engine.compute(ctx["panels"],ctx["resolved_params"])
        raw=ctx["execution_panels"]
        econ={k:raw[k]*raw["__adjust_factor"] if k in {"open","high","low","close"} else raw[k] for k in ("open","high","low","close","volume")}
        names=ctx["panels"].get("__instrument_names__",{})
        econ["__instrument_names__"]=names
        econ["__factor"]=raw["__adjust_factor"]
        if str(econ["close"].index[0])<"2023-01-01":
            raise AssertionError("Unexpected history before retained snapshot")
        days=store.trading_days(start=str(econ["close"].index[0]),end=end)
        if list(econ["close"].index)!=days:
            raise AssertionError("Compressed market calendar")
        at_limit,_,known=strict_price_masks(raw["close"].to_numpy(),raw["close"].to_numpy(),raw["__adjust_factor"].to_numpy(),list(raw["close"].columns),raw["volume"].to_numpy())
        signal_ok=pd.DataFrame(known&~at_limit,index=raw["close"].index,columns=raw["close"].columns)
        return store,ctx,computed,econ,signal_ok
    except Exception:
        store.close()
        raise


def shape_events(panels:dict[str,Any],signal_ok:pd.DataFrame,family:str):
    """An armed platform is fixed; a first close above it always consumes it.

    Missing/invalid bars, floor violation or expiry also consume it. A fresh
    pushing interval must start strictly after the previous terminal date.
    Initial setups may form in 2023 warmup, but no 2023 outcomes are evaluated.
    """
    spec=SHAPES[family];push,pause=spec["push"],spec["pause"]
    o,h,l,c,v=(panels[k] for k in ("open","high","low","close","volume"))
    dates=list(c.index);codes=list(c.columns)
    valid=(np.isfinite(o)&np.isfinite(h)&np.isfinite(l)&np.isfinite(c)&np.isfinite(v)&o.gt(0)&l.gt(0)&c.gt(0)&v.gt(0)&h.ge(o)&h.ge(c)&l.le(o)&l.le(c))
    tr=pd.DataFrame(np.maximum.reduce([(h-l).to_numpy(),(h-c.shift()).abs().to_numpy(),(l-c.shift()).abs().to_numpy()]),index=c.index,columns=c.columns)
    start_c=c.shift(pause+push);end_c=c.shift(pause)
    pushing=(end_c/start_c-1)*100
    upper=h.rolling(pause).max();floor=l.rolling(pause).min()
    width=(upper/floor-1)*100
    tr_ratio=tr.rolling(pause).mean()/tr.rolling(push).mean().shift(pause)
    vol_ratio=v.rolling(pause).mean()/v.rolling(push).mean().shift(pause)
    avg_vol=v.rolling(pause).mean()
    strong=((c/c.shift()-1).ge(.05)&c.gt(o)).rolling(push).max().shift(pause).eq(1)
    retained=floor.ge(start_c+.5*(end_c-start_c))
    clean=pd.Series({code:str(code).startswith(("300","301")) and bool(str(panels["__instrument_names__"].get(str(code),"")).strip()) and "ST" not in str(panels["__instrument_names__"].get(str(code),"")).upper() and "退" not in str(panels["__instrument_names__"].get(str(code),"")) for code in codes})
    factor=panels.get("__factor",pd.DataFrame(1.,index=c.index,columns=c.columns))
    stable_factor=(factor.rolling(push+pause+1).max()/factor.rolling(push+pause+1).min()-1).abs().le(1e-9)
    armed_ok=(valid.rolling(push+pause+1).sum().eq(push+pause+1)&pushing.ge(spec["min_push_pct"])&strong&width.le(spec["max_width_pct"])&tr_ratio.le(spec["max_tr_ratio"])&vol_ratio.le(spec["max_volume_ratio"])&retained&clean&c.notna().cumsum().ge(31)&stable_factor).fillna(False)
    arrays={k:x.to_numpy() for k,x in {"open":o,"high":h,"low":l,"close":c,"volume":v,"factor":factor,"valid":valid,"armed_ok":armed_ok,"upper":upper,"floor":floor,"push_pct":pushing,"tr_ratio":tr_ratio,"vol_ratio":vol_ratio,"avg_volume":avg_vol,"signal_ok":signal_ok}.items()}
    events=[];setups=[]
    for col,code in enumerate(codes):
        state=None;terminal=-1
        for row,date in enumerate(dates):
            if state is not None:
                reason=None
                if row>state["expiry_row"]:
                    reason="expired"
                elif not arrays["valid"][row,col]:
                    reason="missing_or_invalid_bar"
                elif abs(arrays["factor"][row,col]/state["factor_at_arm"]-1)>1e-9:
                    reason="factor_changed_raw_volume_not_comparable"
                elif arrays["low"][row,col]<state["floor"]*.995:
                    reason="floor_violated_first"
                elif arrays["close"][row,col]>state["upper"]:
                    reason="first_price_breakout_consumed"
                    clv=(arrays["close"][row,col]-arrays["low"][row,col])/(arrays["high"][row,col]-arrays["low"][row,col]) if arrays["high"][row,col]>arrays["low"][row,col] else 0.
                    qualify=(arrays["close"][row,col]>=state["upper"]*1.005 and clv>=.65 and arrays["close"][row,col]>arrays["open"][row,col] and arrays["volume"][row,col]>=state["avg_volume"]*1.2 and arrays["signal_ok"][row,col])
                    if qualify:
                        clip=lambda value:min(1.,max(0.,value))
                        score=20*clip(state["push_pct"]/20)+35*clip((1-state["tr_ratio"])/.5)+25*clip((1-state["vol_ratio"])/.5)+20*clv
                        events.append(dict(family=family,signal_date=str(date),code=str(code),row=row,col=col,setup_id=state["setup_id"],arm_date=state["arm_date"],push_start=state["push_start"],push_end=state["push_end"],upper_economic=state["upper"],floor_economic=state["floor"],stop_economic=state["floor"]*.995,score=round(score,4),push_pct=state["push_pct"],tr_ratio=state["tr_ratio"],volume_ratio=state["vol_ratio"],clv=float(clv),signal_risk_pct=(1-state["floor"]*.995/arrays["close"][row,col])*100))
                        reason="first_qualified_breakout"
                if reason:
                    state["terminal_date"]=str(date);state["terminal_reason"]=reason
                    setups.append({k:x for k,x in state.items() if k!="expiry_row"})
                    terminal=row;state=None
            if state is None and arrays["armed_ok"][row,col] and row-pause-push>terminal:
                state=dict(setup_id=f"{family}:{code}:{date}",code=str(code),arm_date=str(date),push_start=str(dates[row-pause-push]),push_end=str(dates[row-pause]),upper=float(arrays["upper"][row,col]),floor=float(arrays["floor"][row,col]),push_pct=float(arrays["push_pct"][row,col]),tr_ratio=float(arrays["tr_ratio"][row,col]),vol_ratio=float(arrays["vol_ratio"][row,col]),avg_volume=float(arrays["avg_volume"][row,col]),factor_at_arm=float(arrays["factor"][row,col]),expiry_row=row+spec["lifetime"])
        if state is not None:
            setups.append({k:x for k,x in {**state,"terminal_date":None,"terminal_reason":"still_armed_at_cutoff"}.items() if k!="expiry_row"})
    return events,setups


def density(db:Path,output:Path):
    output.mkdir(parents=True,exist_ok=True)
    if (output/"density.json").exists():raise FileExistsError("Preserve density evidence")
    before=sources();dbhash=sha256(db)
    write_json(output/"density-plan.json",dict(created_at=now(),shapes=SHAPES,sources=before,snapshot_sha256=dbhash,scope="Training signal density only; 2023 warmup; no forward prices/returns or 2023H2 performance"))
    start,end=SPLITS["train"];store,ctx,computed,econ,signal_ok=prepare(db,start,end)
    try:
        mature=common_maturity_mask(econ["close"].index,start,end,max_hold=10)
        allowed=set(str(d) for d in mature.index[mature]);result={}
        for family in SHAPES:
            events,setups=shape_events(econ,signal_ok,family)
            rows=[r for r in events if r["signal_date"] in allowed]
            active=[r for r in setups if r["arm_date"]>=start]
            pd.DataFrame(rows).to_csv(output/f"density-{family}-events.csv",index=False)
            pd.DataFrame(active).to_csv(output/f"density-{family}-setups.csv",index=False)
            risk=[r["signal_risk_pct"] for r in rows]
            result[family]=dict(events=len(rows),signal_days=len({r["signal_date"] for r in rows}),codes=len({r["code"] for r in rows}),months=len({r["signal_date"][:7] for r in rows}),setups=len(active),signal_risk_le8=sum(x<=8 for x in risk),signal_risk_percentiles=np.quantile(risk,[.1,.5,.9]).tolist() if risk else [],terminal_counts=pd.Series([r["terminal_reason"] for r in active]).value_counts().to_dict())
            print(f"Density {family}: {result[family]}",flush=True)
        if sources()!=before or sha256(db)!=dbhash:raise AssertionError("Density inputs changed")
        write_json(output/"density.json",dict(completed_at=now(),context=context_evidence(ctx),shapes=result,forward_returns_read=False))
    finally:store.close()


class Executor:
    """Research orchestration around the unchanged production exit resolver.

    Entry admission uses opening price only; the structural floor is frozen
    before the signal. Selection never uses any future return.
    """
    def __init__(self,ctx:dict,end:str):
        self.raw=ctx["execution_panels"]
        self.dates=list(self.raw["close"].index);self.codes=list(self.raw["close"].columns)
        self.factor=self.raw["__adjust_factor"].to_numpy()
        self.values={k:self.raw[k].to_numpy() for k in ("open","high","low","close","volume")}
        self.ec={k:self.values[k]*self.factor for k in ("open","high","low","close")}
        self.blocked,self.down,self.known=strict_price_masks(self.values["open"],self.values["close"],self.factor,self.codes,self.values["volume"])
        self.end=end

    def one(self,event:dict,mode:str,is_structure:bool):
        row,col=event["row"],event["col"];entry=row+1
        if entry>=len(self.dates):return None,"entry_beyond_data",None
        raw_open=float(self.values["open"][entry,col])
        if not self.values["volume"][entry,col]>0:return None,"entry_without_positive_volume",None
        if not self.known[entry,col]:return None,"unknown_limit_reference",None
        if self.blocked[entry,col]:return None,"limit_up_open",None
        if not np.isfinite(raw_open) or raw_open<=0:return None,"invalid_open",None
        basis=raw_open*self.factor[entry,col];stop=event.get("stop_economic")
        risk=(1-stop/basis)*100 if is_structure else None
        if is_structure and risk<=0:return None,"open_below_structure_stop",risk
        if is_structure and risk>8:return None,"opening_structure_risk_above8",risk
        cfg=replace(BASELINE.config(self.end),hold_days=9 if mode=="structure10" else 3,stop_loss_pct=-risk if mode=="structure10" else -6.)
        exit_row,price,reason=_resolve_exit(col=col,entry_idx=entry,entry_price=basis,planned_exit=entry+cfg.hold_days,cfg=cfg,
            high_a=self.ec["high"],low_a=self.ec["low"],close_a=self.ec["close"],open_a=self.ec["open"],
            one_word_down=self.down,volume_a=self.values["volume"],last_index=len(self.dates)-1)
        if exit_row is None or reason=="data_end" or not np.isfinite(price) or price<=0:return None,"unresolved_exit_not_zero",risk
        if self.dates[exit_row]>self.end:raise AssertionError("Execution exceeded phase cutoff")
        factor=float(self.factor[exit_row,col]);raw_exit=float(price/factor)
        for field in ("close","open"):
            if price==self.ec[field][exit_row,col]:raw_exit=float(self.values[field][exit_row,col]);break
        window=slice(entry,exit_row+1);good=self.values["volume"][window,col]>0
        highs=self.ec["high"][window,col][good];lows=self.ec["low"][window,col][good];gross=(price/basis-1)*100
        trade=Trade(code=self.codes[col],signal_date=str(self.dates[row]),entry_date=str(self.dates[entry]),entry_price=raw_open,
            exit_date=str(self.dates[exit_row]),exit_price=raw_exit,hold_days=exit_row-entry,gross_return_pct=float(gross),net_return_pct=float(gross-.21),
            mae_pct=float((np.nanmin(lows)/basis-1)*100),mfe_pct=float((np.nanmax(highs)/basis-1)*100),exit_reason=reason,
            entry_factor=float(self.factor[entry,col]),exit_factor=factor)
        return trade,"filled",risk


def metric_bundle(trades:list[Trade],budget:int):
    winner=max(trades,key=lambda t:t.net_return_pct) if trades else None;without=[t for t in trades if t is not winner];result={}
    for name,rows,cost in (("base",trades,.21),("double_cost",trades,.42),("winner_removed",without,.21),("double_cost_winner_removed",without,.42)):
        m=independent_metrics(rows,cost);m["common_slot_mean"]=sum(t.gross_return_pct-cost for t in rows)/budget if budget else None;result[name]=m
    result.update(worst_net=min((t.net_return_pct for t in trades),default=None),average_hold_sessions_including_entry=float(np.mean([t.hold_days+1 for t in trades])) if trades else None,
        max_hold_sessions_including_entry=max((t.hold_days+1 for t in trades),default=None),largest_winner=winner.to_dict(include_factors=True) if winner else None)
    return result


def events_for_original(computed,signal_ok,dates,corrected:bool):
    scores=computed.factors["score"];mask=computed.factors["条件候选"].fillna(False).astype(bool)&scores.notna()
    if corrected:mask&=signal_ok
    else:mask=computed.signals.fillna(False).astype(bool)
    rows,cols=np.nonzero(mask.to_numpy())
    return [dict(signal_date=str(dates[r]),code=str(scores.columns[c]),row=int(r),col=int(c),score=float(scores.iloc[r,c]),setup_id=None) for r,c in zip(rows,cols)]


def execute(events:list[dict],variant:str,allowed:list[str],executor:Executor,output:Path,segment:str):
    spec=VARIANTS[variant];allowed_set=set(allowed);byday=defaultdict(list)
    for e in events:
        if e["signal_date"] in allowed_set:byday[e["signal_date"]].append(e)
    held_until={};selected=[];trades=[];skips=Counter();held_exclusions=0;date_index={str(d):i for i,d in enumerate(executor.dates)}
    for date in allowed:
        row=date_index[date];ranked=sorted(byday[date],key=lambda e:(-e["score"],e["code"]));free=[]
        for event in ranked:
            if spec["deduplicate"] and held_until.get(event["code"],-1)>row:held_exclusions+=1
            else:free.append(event)
        # Commit the two names before checking their next opening admission.
        for event in free[:2]:
            trade,status,risk=executor.one(event,spec["exit"],spec["family"]!="original")
            if status=="unresolved_exit_not_zero":raise AssertionError("Unknown exit cannot be zero-filled or nominated")
            if trade is not None:trades.append(trade);held_until[event["code"]]=date_index[trade.exit_date]
            else:skips[status]+=1
            selected.append({**event,"entry_date":str(executor.dates[event["row"]+1]),"entry_open_raw":float(executor.values["open"][event["row"]+1,event["col"]]),
                "entry_factor":float(executor.factor[event["row"]+1,event["col"]]),"opening_structure_risk_pct":risk,"status":status,"net_return_pct":trade.net_return_pct if trade else 0.})
    if len(selected)!=len(trades)+sum(skips.values()):raise AssertionError("Order accounting mismatch")
    for code in set(t.code for t in trades):
        rows=sorted([t for t in trades if t.code==code],key=lambda t:t.entry_date)
        if spec["deduplicate"] and any(b.entry_date<=a.exit_date for a,b in zip(rows,rows[1:])):raise AssertionError("Overlapping holdings of one code")
    occupancy=[sum(t.entry_date<=str(d)<=t.exit_date for t in trades) for d in executor.dates]
    pd.DataFrame(selected).to_csv(output/f"{segment}-{variant}-orders.csv",index=False)
    pd.DataFrame([t.to_dict(include_factors=True) for t in trades]).to_csv(output/f"{segment}-{variant}-trades.csv",index=False)
    totals=Counter()
    for t in trades:totals[t.signal_date]+=t.net_return_pct
    daily=pd.DataFrame([dict(segment=segment,variant=variant,signal_date=d,opportunities=2,net_sum=totals[d]) for d in allowed])
    return dict(metrics=metric_bundle(trades,2*len(allowed)),candidate_events=sum(len(x) for x in byday.values()),candidate_days=sum(bool(x) for x in byday.values()),
        planned_orders=len(selected),closed=len(trades),skipped=dict(skips),held_candidate_exclusions=held_exclusions,filled_slot_pct=100*len(trades)/(2*len(allowed)),
        closed_months=len({t.signal_date[:7] for t in trades}),max_concurrent_positions=max(occupancy,default=0),same_code_overlap_allowed=not spec["deduplicate"]),trades,daily


def evaluate(db:Path,output:Path,segment:str,variants:list[str]):
    start,end=SPLITS[segment];store,ctx,computed,econ,signal_ok=prepare(db,start,end)
    try:
        index=econ["close"].index;mask=common_maturity_mask(index,start,end,max_hold=COMMON_MATURITY);allowed=[str(d) for d in index[mask]];allowed_set=set(allowed);executor=Executor(ctx,end)
        old_candidates=computed.factors["条件候选"].fillna(False).astype(bool)&computed.factors["score"].notna()
        correction_count=int((old_candidates&~signal_ok).where(mask,False,axis=0).to_numpy().sum());cache={}
        for family in sorted({VARIANTS[v]["family"] for v in variants}-{"original"}):
            events,setups=shape_events(econ,signal_ok,family);cache[family]=events
            pd.DataFrame([e for e in events if e["signal_date"] in allowed_set]).to_csv(output/f"{segment}-{family}-events.csv",index=False)
            pd.DataFrame([s for s in setups if s["arm_date"]>=start]).to_csv(output/f"{segment}-{family}-setups.csv",index=False)
            cutoff=index[len(index)*2//3];prefix={k:v.loc[:cutoff] if isinstance(v,pd.DataFrame) else v for k,v in econ.items()}
            early,_=shape_events(prefix,signal_ok.loc[:cutoff],family)
            if early!=[e for e in events if e["signal_date"]<=cutoff]:raise AssertionError(f"Noncausal setup state: {family}")
        legacy_events=events_for_original(computed,signal_ok,index,False);flat_events=events_for_original(computed,signal_ok,index,True)
        oldkeys={(e["signal_date"],e["code"]) for e in legacy_events if e["signal_date"] in allowed_set};old_dates={d for d,c in oldkeys}
        rows={};trades_by={};dailies=[];baseline_daily=None
        for variant in variants:
            family=VARIANTS[variant]["family"];events=legacy_events if variant=="legacy_original4" else flat_events if family=="original" else cache[family]
            result,trades,daily=execute(events,variant,allowed,executor,output,segment)
            if variant=="legacy_original4":
                classic=run_backtest(computed.signals.where(mask,False,axis=0),ctx["execution_panels"],entry_timing="next_open",config=BASELINE.config(end))
                found={(t.signal_date,t.code):t for t in classic.trades}
                if len(found)!=len(trades):raise AssertionError("Legacy adapter/classic count mismatch")
                for t in trades:
                    old=found[(t.signal_date,t.code)]
                    if (old.entry_date,old.exit_date,old.exit_reason)!=(t.entry_date,t.exit_date,t.exit_reason) or not np.isclose(old.net_return_pct,t.net_return_pct,atol=1e-9,rtol=0):raise AssertionError("Legacy adapter differs from classic execution")
            if variant=="baseline_flat4":baseline_daily=daily.set_index("signal_date").net_sum
            outcomes={(t.signal_date,t.code):t for t in trades}
            oldrows=[dict(signal_date=d,code=c,new_selected=(d,c) in outcomes,new_net_pct=outcomes[(d,c)].net_return_pct if (d,c) in outcomes else 0.) for d,c in sorted(oldkeys)]
            pd.DataFrame(oldrows).to_csv(output/f"{segment}-{variant}-legacy-opportunities.csv",index=False)
            new=[t for key,t in outcomes.items() if key not in oldkeys]
            pd.DataFrame([t.to_dict(include_factors=True) for t in new]).to_csv(output/f"{segment}-{variant}-new-opportunities.csv",index=False)
            result.update(legacy_opportunities=len(oldkeys),legacy_overlap_trades=len(trades)-len(new),new_opportunity_trades=len(new),new_opportunity_net_sum=sum(t.net_return_pct for t in new),trades_on_previously_inactive_dates=sum(t.signal_date not in old_dates for t in trades))
            rows[variant]=result;trades_by[variant]=trades;dailies.append(daily);m=result["metrics"]["base"]
            print(f"{segment}/{variant}: trades={len(trades)} slots={2*len(allowed)} mean={m['avg_net_return']} PF={m['profit_factor']} slot={m['common_slot_mean']}",flush=True)
        for daily in dailies:
            daily["base_net_sum"]=daily.signal_date.map(baseline_daily);daily["delta_net_sum"]=daily.net_sum-daily.base_net_sum
            rows[str(daily.variant.iloc[0])]["paired_bootstrap"]=paired_bootstrap(daily)
        return dict(context=context_evidence(ctx),common_maturity_sessions=COMMON_MATURITY,common_market_days=len(allowed),common_daily_slots=2*len(allowed),first_signal_day=allowed[0],last_signal_day=allowed[-1],corrected_original_candidate_exclusions=correction_count,runs=rows),trades_by,dailies
    finally:store.close()


def nominate(result:dict):
    runs=result["runs"];base=runs["baseline_flat4"]["metrics"]["base"];budget=[];quality=[]
    for v,r in runs.items():
        if v in CONTROLS:continue
        m=r["metrics"];b=m["base"];pf=b["profit_factor"] if b["profit_factor"] is not None else (math.inf if b["wins"] else 0)
        if b["trades"]>=20 and r["closed_months"]>=4 and b["avg_net_return"]>0 and pf>1 and m["double_cost"]["avg_net_return"]>0 and m["winner_removed"]["avg_net_return"]>0:
            if b["common_slot_mean"]>base["common_slot_mean"]:budget.append(v)
            if b["avg_net_return"]>base["avg_net_return"] and pf>(base["profit_factor"] or 0):quality.append(v)
    budget.sort(key=lambda v:(-runs[v]["metrics"]["base"]["common_slot_mean"],v));quality.sort(key=lambda v:(-runs[v]["metrics"]["double_cost_winner_removed"]["avg_net_return"],-runs[v]["metrics"]["base"]["common_slot_mean"],v))
    chosen=budget[:1];chosen.extend([v for v in quality if v not in chosen][:1]);return chosen


def run_study(db:Path,output:Path):
    density_path=output/"density-final/density.json"
    if not density_path.exists():raise ValueError("Final guarded training density required first")
    if (output/"PLAN.json").exists():raise FileExistsError("Do not overwrite frozen research")
    before=sources();dbhash=sha256(db)
    plan=dict(created_at=now(),shapes=SHAPES,variants=VARIANTS,splits=SPLITS,snapshot_sha256=dbhash,sources=before,density_path="density-final/density.json",density_sha256=sha256(density_path),
        setup="At S close: push C(S-K)/C(S-K-P)-1 reaches family threshold, with at least one bullish >=5% day in that P-session push; K-session box width=HH/LL-1 within cap, mean TR ratio and volume ratio to push within caps, box low retains >=half push close advance. All P+K+1 bars valid/positive-volume, >=31 observed bars; clean ChiNext universe.",
        state="Arm S after close; freeze box high/low, mean volume and setup components. Later low<floor*0.995 invalidates before any breakout; missing/invalid bar or expiry consumes too. First close>frozen high consumes whether quality passes or not, including non-Top2. New push start must follow last terminal date. No rolling expansion after arming.",
        volume_comparability="No split/share adjustment series: raw volume is never adjusted by total-return factor. Conservatively forbid arming across any economic-factor change in the P+K+1 setup window, and invalidate an armed platform if that factor changes before first breakout. This also excludes cash-dividend events; no later-outcome-based exemptions.",
        breakout="First closing-price crossing C>frozen upper consumes the setup; intraday H-only crossing does not. That first close crossing qualifies only C>=upper*1.005,C>O,CLV=(C-L)/(H-L)>=0.65,V>=setup_volume*1.2,corrected economic-reference raw close below upper limit. No fixed two-day decline or signal-day >=3% requirement.",
        legacy_limit_correction="Fair baseline intersects existing original shape candidates with economic-reference below-limit. This removes false admissions but cannot restore hypothetical exclusions caused by a factor decrease. Read-only training metadata audit found zero material factor decreases during2023-01-01..2025-06-30; do not claim all original price logic was repaired. New shape universe independently applies the economic-reference contract.",
        score="20*clip(push_pct/20)+35*clip((1-TR_ratio)/0.5)+25*clip((1-volume_ratio)/0.5)+20*CLV; clip0..1,round4,code tie; setup parts frozen at arm, CLV signal-day only.",
        execution="Next-day opening-conditional proxy. New-family orders cancelled if actual open<=floor*0.995 or distance to that fixed stop>8%; no same-day H/L/C entry admission or post-cancel refill. 4-session/-6% or10-session/fixed platform stop, no trailing widening. Raw fill/economic factor; unchanged _resolve_exit T+1/limit/suspension/gap rules. No historical auction quote availability claim.",
        duplicate_control="At signal close remove codes still held after that close, then rank full events Top2. Actual exits on/before signal date are past-known. Setups consumed independently of selection. Legacy control allows original repeated events; fair baseline deduplicates and corrects limit reference.",
        budget="Every common mature market day x2 including zero-signal/new dates.20-session maturity for10-session holding plus deferred-sale buffer; unknown exits not zero. Original opportunity overlap/new contribution retained separately. Independent event slots are not fixed-capital NAV.",
        nomination="Train only,at most2: >=20 closed across4months,mean>0,PF>1,double-cost and winner-removed mean>0. Budget rep highest fixed-slot mean above fair baseline; distinct quality rep trade mean/PF>fair baseline, highest double-cost-winner-removed trade mean then slot mean. No later rescue.",
        acceptance="Both later segments have trades,mean>0 and PF>1; post-train pooled double-cost,winner-removed,and combined double-cost-winner-removed means>0; common-slot improvement/idle cost vs fair baseline and month-block CI public. Subsequent fixed-capital portfolio test still required.",cost_pct=.21,stress_cost_pct=.42,
        limitations=["2024-2026 already observed: retrospective, multiple development bias","2023 indicator/state warmup only;2023H2 forward returns withheld","Current catalog/names/factor revisions not strict PIT; economic-reference limits are contract values,not official ex-right notices","Daily opening conditions do not prove auction fills or queues","Different-code overlap; no total capital limit; holdings/concurrency exposed","Whole entry/exit-bar MAE/MFE not used for decisions"])
    write_json(output/"PLAN.json",plan);write_json(output/"freeze-receipt.json",dict(created_at=now(),plan_sha256=sha256(output/"PLAN.json")))
    summary=dict(plan_sha256=sha256(output/"PLAN.json"),segments={});alltrades=defaultdict(list);alldaily=[];nominees=[]
    for segment in SPLITS:
        if sources()!=before:raise AssertionError("Sources changed after freeze")
        variants=list(VARIANTS) if segment=="train" else [*CONTROLS,*nominees]
        result,trades,daily=evaluate(db,output,segment,variants);summary["segments"][segment]=result;write_json(output/f"{segment}-summary.json",result)
        for key,items in trades.items():alltrades[key].extend(items)
        alldaily.extend(daily)
        if segment=="train":
            nominees=nominate(result);summary["training_nominees"]=nominees
            write_json(output/"training-nomination.json",dict(created_at=now(),nominees=nominees,plan_sha256=summary["plan_sha256"],train_sha256=sha256(output/"train-summary.json")))
    daily=pd.concat(alldaily,ignore_index=True);daily.to_csv(output/"paired-daily-results.csv",index=False);summary["pooled"]={}
    for variant in [*CONTROLS,*nominees]:
        frame=daily[daily.variant.eq(variant)];later=frame[frame.segment.ne("train")];post=[t for t in alltrades[variant] if t.signal_date>="2025-07-01"]
        entry=dict(metrics=metric_bundle(alltrades[variant],int(frame.opportunities.sum())),post_train_metrics=metric_bundle(post,int(later.opportunities.sum())),paired_bootstrap=paired_bootstrap(frame),post_train_bootstrap=paired_bootstrap(later))
        if variant not in CONTROLS:
            m=entry["post_train_metrics"]
            entry["passes_statistical_stage"]=all(summary["segments"][seg]["runs"][variant]["metrics"]["base"]["trades"]>0 and summary["segments"][seg]["runs"][variant]["metrics"]["base"]["avg_net_return"]>0 and (summary["segments"][seg]["runs"][variant]["metrics"]["base"]["profit_factor"] or 0)>1 for seg in ("validation_2025h2","observed_2026")) and all(m[name]["avg_net_return"] is not None and m[name]["avg_net_return"]>0 for name in ("double_cost","winner_removed","double_cost_winner_removed"))
        summary["pooled"][variant]=entry
    if sources()!=before or sha256(db)!=dbhash:raise AssertionError("Source/snapshot changed")
    summary.update(completed_at=now(),source_and_snapshot_unchanged=True,withheld_2023h2_not_evaluated=True);write_json(output/"summary.json",summary)
    pd.DataFrame([dict(segment=seg,variant=v,**r["metrics"]["base"],filled_slot_pct=r["filled_slot_pct"],avg_hold=r["metrics"]["average_hold_sessions_including_entry"],max_concurrent=r["max_concurrent_positions"]) for seg,d in summary["segments"].items() for v,r in d["runs"].items()]).to_csv(output/"metrics.csv",index=False)
    print(json.dumps(dict(output=str(output),nominees=nominees,passed={v:r.get("passes_statistical_stage") for v,r in summary["pooled"].items() if v not in CONTROLS})),flush=True)


def self_check():
    dates=pd.bdate_range("2024-01-01",periods=60).strftime("%Y-%m-%d");code="300001"
    p={k:pd.DataFrame(v,index=dates,columns=[code]) for k,v in {"open":100.,"high":101.,"low":99.,"close":100.,"volume":100.}.items()}
    for row,close_ in zip(range(40,45),[106.,108.,110.,111.,112.]):
        p["open"].iloc[row,0]=100. if row==40 else p["close"].iloc[row-1,0];p["close"].iloc[row,0]=close_;p["high"].iloc[row,0]=close_+1;p["low"].iloc[row,0]=p["open"].iloc[row,0]-1;p["volume"].iloc[row,0]=200.
    for row in (45,46,47):
        for k,value in {"open":112.,"high":112.5,"low":111.5,"close":112.,"volume":60.}.items():p[k].iloc[row,0]=value
    for row in (48,49):
        for k,value in {"open":112.5,"high":114.5,"low":112.,"close":114.,"volume":100.}.items():p[k].iloc[row,0]=value
    p["volume"].iloc[44,0]=500.
    p["__instrument_names__"]={code:"sample"};ok=pd.DataFrame(True,index=dates,columns=[code]);events,_=shape_events(p,ok,"compact3")
    assert len(events)==1 and events[0]["signal_date"]==dates[48]
    assert events[0]["upper_economic"]==112.5 and events[0]["floor_economic"]==111.5
    weak={k:v.copy() if isinstance(v,pd.DataFrame) else v for k,v in p.items()};weak["close"].iloc[48,0]=112.7;assert shape_events(weak,ok,"compact3")[0]==[]
    both={k:v.copy() if isinstance(v,pd.DataFrame) else v for k,v in p.items()};both["low"].iloc[48,0]=109.;assert shape_events(both,ok,"compact3")[0]==[]
    prefix={k:v.iloc[:49] if isinstance(v,pd.DataFrame) else v for k,v in p.items()};assert shape_events(prefix,ok.iloc[:49],"compact3")[0]==events
    raw={k:v.copy() for k,v in p.items() if isinstance(v,pd.DataFrame)};raw["__adjust_factor"]=pd.DataFrame(1.,index=dates,columns=[code]);ex=Executor({"execution_panels":raw},str(dates[-1]));event=dict(row=38,col=0,code=code,stop_economic=99.)
    ex.values["open"]=ex.values["open"].copy()
    ex.values["open"][39,0]=98.;ex.ec["open"][39,0]=98.;assert ex.one(event,"structure10",True)[1]=="open_below_structure_stop"
    ex.values["open"][39,0]=110.;ex.ec["open"][39,0]=110.;assert ex.one(event,"structure10",True)[1]=="opening_structure_risk_above8"
    print("Passed: frozen arm bounds, weak first crossing consumed, floor violation first, prefix causality, opening-stop and8% risk cancellation",flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=["density","run","self-check"])
    parser.add_argument("--db",type=Path)
    parser.add_argument("--output",type=Path,default=OUTPUT)
    args=parser.parse_args()
    if args.phase=="self-check":self_check();return
    if args.db is None:parser.error("--db required")
    action=density if args.phase=="density" else run_study
    action(args.db.resolve(strict=True),args.output.resolve())


if __name__=="__main__":main()
