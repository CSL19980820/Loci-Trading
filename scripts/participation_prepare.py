"""Independent platform breakouts plus existing pullback setups, on frozen inputs."""
import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.high_payoff_research import load_frame
from scripts.limitup_rightside_features import GENERIC_EVENT_LABELS, add_theme_evidence, read_events


def platform_features(frame):
    price = frame[['open', 'high', 'low', 'close']].mul(frame.factor, axis=0)
    ceiling = price.high.rolling(10).max().shift(1)
    floor = price.low.rolling(10).min().shift(1)
    width = ceiling / floor - 1
    clv = (price.close - price.low) / (price.high - price.low).replace(0, np.nan)
    signal = (price.close > ceiling) & (width <= .20)
    signal &= price.close >= price.high.rolling(60).max().shift(1) * .97
    signal &= frame.volume >= frame.volume.rolling(20).median().shift(1) * 1.2
    signal &= (price.close > price.open) & (clv >= .65) & (frame.close >= 5)
    signal &= (frame.close * frame.volume).rolling(20).median().shift(1) >= 50_000_000
    return pd.DataFrame({'signal': signal.fillna(False), 'level': ceiling,
                         'stop': price.low * .995, 'clv': clv})


def main(root, output):
    db = sqlite3.connect((root / 'market-frozen.db').resolve().as_uri() + '?mode=ro', uri=True)
    events = read_events(root / 'event-pages', 'train') + read_events(root / 'event-pages', 'validation')
    dates = [r[0] for r in db.execute('SELECT trade_date FROM trading_calendar ORDER BY trade_date')]
    ix = {d: i for i, d in enumerate(dates)}
    code_events = defaultdict(list)
    for event in events:
        code_events[event['code']].append(event)
    universe = db.execute("SELECT code,name,list_date FROM instruments WHERE instrument_type='STOCK' "
        "AND (code LIKE '00%' OR code LIKE '60%' OR code LIKE '30%') AND upper(name) NOT LIKE '%ST%' "
        "AND name NOT LIKE '%退%' ORDER BY code").fetchall()
    old = json.loads((root / 'prepared/candidates.json').read_text(encoding='utf-8'))
    needed = {r['code'] for r in old}
    frames, closes, candidates = {}, {}, []
    for n, (code, name, listed) in enumerate(universe):
        frame = load_frame(db, code, dates)
        close = frame.close * frame.factor
        closes[code] = close
        computed = platform_features(frame)
        event_list = code_events[code]
        cursor, last = 0, None
        for day in computed.index[computed.signal]:
            if not '02-01' <= day[5:] <= '08-31' or day[:4] not in ('2025', '2026'):
                continue
            while cursor < len(event_list) and event_list[cursor]['day'] <= day:
                last = event_list[cursor];cursor += 1
            if not last or ix[day] - ix[last['day']] > 60 or last['primaryTheme'] in GENERIC_EVENT_LABELS:
                continue
            if not listed or (pd.Timestamp(day) - pd.Timestamp(listed)).days < 180:
                continue
            r = computed.loc[day];i=ix[day]
            candidates.append({'code':code,'name':name,'signal_date':day,'theme':last['primaryTheme'],
                'anchor_date':last['day'],'anchor_amount':float(last.get('tradingAmount') or 0),
                'stop_level':float(r.stop),'retest_level':float(r.level),'confirmation_close':float(close.iloc[i]),
                'daily_return_pct':float((close.iloc[i]/close.iloc[i-1]-1)*100),'clv':float(r.clv),
                'setup':'platform'})
            needed.add(code)
        if code in needed:frames[code]=frame
        if n % 1000 == 0:print('prepared',n,len(universe),flush=True)
    candidates=add_theme_evidence(candidates,events,pd.DataFrame(closes))
    for row in old:
        frame=frames[row['code']];i=ix[row['signal_date']]
        row['retest_level']=float((frame.high*frame.factor).iloc[i-2:i].max())
        row['setup']='pullback'
    candidates.extend(old)
    codes=sorted(frames)
    output.mkdir(parents=True,exist_ok=True)
    (output/'candidates.json').write_text(json.dumps(candidates,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    arrays={f:np.column_stack([frames[c][f].to_numpy(dtype=float) for c in codes]) for f in ('open','high','low','close','volume','factor')}
    np.savez_compressed(output/'execution.npz',dates=np.array(dates),codes=np.array(codes),**arrays)
    print(json.dumps({'candidates':len(candidates),'platform':len(candidates)-len(old),'codes':len(codes)}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.root,a.output)
