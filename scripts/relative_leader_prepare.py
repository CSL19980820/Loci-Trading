"""Find pullbacks that retain a large advantage over a declared thematic index."""
import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.high_payoff_research import load_frame
from scripts.limitup_rightside_features import read_events

BENCHMARKS = {
    '980022': ['机器人','机器人概念','人形机器人','工业机器人'],
    '980017': ['芯片','半导体','存储芯片','半导体设备','先进封装'],
    '399389': ['通信','通信设备','光通信','光模块','CPO'],
    '399368': ['军工','军工概念'],
    '980027': ['新能源电池','锂电池','锂电产业链','电池产业链','固态电池'],
}


def load_indices(folder, dates):
    output={}
    for code in BENCHMARKS:
        data=json.loads((folder/(code+'-cni.json')).read_text(encoding='utf-8'))['payload']['data']
        frame=pd.DataFrame(data['data'],columns=data['item'])
        days=pd.to_datetime(frame.timestamp,unit='ms',utc=True).dt.tz_convert('Asia/Shanghai').dt.strftime('%Y-%m-%d')
        series=pd.Series(frame.close.to_numpy(dtype=float),index=days).sort_index()
        assert not series.index.duplicated().any()
        output[code]=series.reindex(dates)
        assert output[code].notna().all(), code
    return output


def pullback_shape(frame):
    price=frame[['open','high','low','close']].mul(frame.factor,axis=0)
    peak=price.high.rolling(12).max().shift(3)
    recent_high=price.high.rolling(2).max().shift(1)
    trough=price.low.rolling(3).min()
    draw=1-trough/peak
    clv=(price.close-price.low)/(price.high-price.low).replace(0,np.nan)
    shape=(draw.between(.03,.15) & (recent_high<peak) & (price.close>price.high.shift(1))
           & (price.close>price.open) & (clv>=.6) & (frame.close>=5)
           & (frame.volume>=frame.volume.rolling(3).median().shift(1)*1.1)
           & ((frame.close*frame.volume).rolling(20).median().shift(1)>=50_000_000))
    return price,pd.DataFrame({'signal':shape.fillna(False),'trough':trough,'drawdown':draw,'clv':clv})


def relative_values(close, benchmark, peak, today):
    stock_peak=close.iloc[peak]/close.iloc[peak-20]-1
    bench_peak=benchmark.iloc[peak]/benchmark.iloc[peak-20]-1
    now20=(close.iloc[today]/close.iloc[today-20]-1)-(benchmark.iloc[today]/benchmark.iloc[today-20]-1)
    now40=(close.iloc[today]/close.iloc[today-40]-1)-(benchmark.iloc[today]/benchmark.iloc[today-40]-1)
    if not np.isfinite([stock_peak,bench_peak,now20,now40]).all():
        return None
    strong=stock_peak>=.25 and stock_peak-bench_peak>=.15 and now20>=.10 and now40>=0
    return {'stock_peak20_pct':float(stock_peak*100),'index_peak20_pct':float(bench_peak*100),
            'excess_peak20_pp':float((stock_peak-bench_peak)*100),'excess_now20_pp':float(now20*100),
            'excess_now40_pp':float(now40*100),'index_now20_pct':float((benchmark.iloc[today]/benchmark.iloc[today-20]-1)*100),
            'relative_leader':bool(strong)}


def main(source, root):
    db=sqlite3.connect((source/'market-frozen.db').resolve().as_uri()+'?mode=ro',uri=True)
    dates=[r[0] for r in db.execute('SELECT trade_date FROM trading_calendar ORDER BY trade_date')]
    di={d:i for i,d in enumerate(dates)};indices=load_indices(root/'indices',dates)
    mapping={name:code for code,names in BENCHMARKS.items() for name in names}
    events=read_events(source/'event-pages','train')+read_events(source/'event-pages','validation')
    by_code=defaultdict(list)
    for event in events:by_code[event['code']].append(event)
    universe=db.execute("SELECT code,name,list_date FROM instruments WHERE instrument_type='STOCK' "
        "AND (code LIKE '00%' OR code LIKE '60%' OR code LIKE '30%') AND upper(name) NOT LIKE '%ST%' "
        "AND name NOT LIKE '%退%' ORDER BY code").fetchall()
    frames,candidates={},[]
    for number,(code,name,listed) in enumerate(universe):
        if not any(e['primaryTheme'] in mapping for e in by_code[code]):continue
        frame=load_frame(db,code,dates);price,shape=pullback_shape(frame);cursor=0;last=None;rows=[]
        for day in shape.index[shape.signal]:
            if day[:4] not in ('2025','2026') or not '02-01'<=day[5:]<='08-31':continue
            i=di[day]
            while cursor<len(by_code[code]) and by_code[code][cursor]['day']<=day:
                last=by_code[code][cursor];cursor+=1
            if not last or last['primaryTheme'] not in mapping or i-di[last['day']]>60:continue
            if not listed or (pd.Timestamp(day)-pd.Timestamp(listed)).days<180:continue
            window=price.iloc[i-14:i-2]
            if window.high.isna().any():continue
            peak=i-14+int(np.argmax(window.high.to_numpy()))
            if peak<20 or i<40:continue
            benchmark_code=mapping[last['primaryTheme']];benchmark=indices[benchmark_code]
            stats=relative_values(price.close,benchmark,peak,i)
            # The control shares the same absolute strong run-up and pullback, without the relative gate.
            if stats is None or stats['stock_peak20_pct']<25:continue
            b1=(benchmark.iloc[i]/benchmark.iloc[i-1]-1)*100
            s1=(price.close.iloc[i]/price.close.iloc[i-1]-1)*100
            s5=(price.close.iloc[i]/price.close.iloc[i-5]-benchmark.iloc[i]/benchmark.iloc[i-5])*100
            rows.append({'code':code,'name':name,'signal_date':day,'theme':last['primaryTheme'],
                'benchmark_code':benchmark_code,'anchor_date':dates[peak],'peak_date':dates[peak],
                'anchor_amount':float(last.get('tradingAmount') or 0),'stop_level':float(shape.trough.loc[day]*.995),
                'retest_level':float(price.high.iloc[i-1]),'confirmation_close':float(price.close.iloc[i]),
                'daily_return_pct':float(s1),'clv':float(shape.clv.loc[day]),'drawdown_pct':float(shape.drawdown.loc[day]*100),
                'setup':'pullback','origin':'relative_index','peer_return_pct':float(b1),'peer_breadth':None,
                'leg_retrace_fraction':float((price.high.iloc[peak]-shape.trough.loc[day])/(price.high.iloc[peak]-price.close.iloc[peak-20])),
                'market_return_pct':None,'market_breadth':None,'excess_five_day_pct':float(s5),
                'resonance':bool(b1>0),'independent':bool(s1-b1>=3),'theme_limitups_today':None,
                'theme_count_rank_fraction':None,**stats})
        if rows:frames[code]=frame;candidates.extend(rows)
        if number%500==0:print('processed',number,'candidates',len(candidates),flush=True)
    codes=sorted(frames);prepared=root/'prepared';prepared.mkdir(exist_ok=True)
    (prepared/'candidates.json').write_text(json.dumps(candidates,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    arrays={f:np.column_stack([frames[c][f].to_numpy(dtype=float) for c in codes]) for f in ['open','high','low','close','volume','factor']}
    np.savez_compressed(prepared/'execution.npz',dates=np.array(dates),codes=np.array(codes),**arrays)
    (root/'benchmark-map.json').write_text(json.dumps(BENCHMARKS,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'candidates':len(candidates),'relative_leaders':sum(r['relative_leader'] for r in candidates),
                      'by_year':{y:sum(r['relative_leader'] and r['signal_date'].startswith(y) for r in candidates) for y in ['2025','2026']}}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--root',type=Path,required=True)
    a=p.parse_args();main(a.source,a.root)
