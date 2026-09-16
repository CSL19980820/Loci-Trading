"""Dated limit-up anchors, pullback confirmation and lagged theme-peer evidence."""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.high_payoff_research import load_frame

GENERIC_EVENT_LABELS = {'公告', '其他', '其他类', '业绩', 'ST股', 'ST', '摘帽', '业绩增长', '公告利好'}

def read_events(directory: Path, prefix: str) -> list[dict]:
    pages = sorted(directory.glob(prefix + '-*.json'))
    if not pages:
        return []
    rows, expected = [], None
    for number, path in enumerate(pages, 1):
        block = json.loads(path.read_text(encoding='utf-8'))['data']
        assert block['pagination']['page'] == number, path
        assert block['returned'] == len(block['rows']), path
        expected = block['total'] if expected is None else expected
        assert expected == block['total'], 'Source total changed during pagination'
        rows.extend(block['rows'])
    assert len(rows) == expected, (prefix, len(rows), expected)
    assert len({(r['date'], r['code']) for r in rows}) == len(rows), 'Duplicate events across pages'
    for row in rows:
        row['day'] = pd.Timestamp(row['date']).strftime('%Y-%m-%d')
    return sorted(rows, key=lambda r: (r['day'], r['code']))


def stock_candidates(frame: pd.DataFrame, events: list[dict], listed: str) -> list[dict]:
    """A two-bar pullback must precede the right-side trigger; no moving average signal."""
    dates = list(frame.index)
    by_day = {r['day']: r for r in events}
    price = frame[['open', 'high', 'low', 'close']].mul(frame.factor, axis=0)
    out, anchor, used = [], None, False
    for idx, day in enumerate(dates):
        if day in by_day:
            event = by_day[day]
            event_close = float(event.get('latest') or 0)
            raw_close = float(frame.close.iloc[idx])
            valid = (1 <= int(event.get('continueNum') or 0) <= 3
                     and float(event.get('tradingAmount') or 0) >= 100_000_000
                     and bool(event.get('primaryTheme'))
                     and np.isfinite(raw_close) and event_close > 0
                     and abs(event_close - raw_close) <= max(.02, raw_close * .001))
            anchor = (idx, event) if valid else None
            used = False
            continue
        if anchor is None or used or idx < 20:
            continue
        ai, event = anchor
        if not 3 <= idx - ai <= 12:
            continue
        if not listed or (pd.Timestamp(day) - pd.Timestamp(listed)).days < 180:
            continue
        history = price.iloc[ai:idx + 1]
        volumes = frame.volume.iloc[ai:idx + 1]
        if history.isna().any().any() or (volumes <= 0).any():
            continue
        # Large corporate-action changes would distort raw-share volume comparisons.
        if frame.factor.iloc[ai:idx + 1].max() / frame.factor.iloc[ai:idx + 1].min() > 1.10:
            continue
        peak_offset = int(np.argmax(history.high.iloc[:-1].to_numpy()))
        pullback = history.iloc[peak_offset + 1:-1]
        pull_vol = volumes.iloc[peak_offset + 1:-1]
        if len(pullback) < 2:
            continue
        peak = float(history.high.iloc[peak_offset])
        support = float(pullback.low.min())
        depth = 1 - support / peak
        if not .03 <= depth <= .15:
            continue
        if support < float(history.open.iloc[0]) * .98:
            continue
        shrink = float(pull_vol.median() / volumes.iloc[0])
        if shrink > .75:
            continue
        row, previous = history.iloc[-1], history.iloc[-2]
        typical = (history.high + history.low + history.close) / 3
        anchored_price = float((typical * volumes).sum() / volumes.sum())
        clv = float((row.close - row.low) / (row.high - row.low)) if row.high > row.low else 0
        daily_return = float(row.close / previous.close - 1)
        if not (row.close > history.high.iloc[-3:-1].max()
                and row.close > anchored_price and row.close > row.open
                and clv >= .65 and .015 <= daily_return <= .085
                and volumes.iloc[-1] >= pull_vol.median() * 1.2):
            continue
        if frame.close.iloc[idx] < 5:
            continue
        used = True
        out.append({'code': event['code'], 'name': event['name'], 'signal_date': day,
                    'anchor_date': dates[ai], 'theme': event['primaryTheme'],
                    'anchor_continue_num': int(event['continueNum']),
                    'anchor_type': event.get('limitUpType'),
                    'anchor_amount': float(event['tradingAmount']),
                    'stop_level': support * .995, 'confirmation_close': float(row.close),
                    'anchored_typical_price': anchored_price, 'pullback_depth_pct': depth * 100,
                    'pullback_days': len(pullback), 'anchor_age': idx - ai,
                    'shrink_ratio': shrink, 'clv': clv,
                    'rebound_volume_ratio': float(volumes.iloc[-1] / pull_vol.median()),
                    'daily_return_pct': daily_return * 100})
    return out


def add_theme_evidence(candidates: list[dict], events: list[dict], close: pd.DataFrame) -> list[dict]:
    """Peers come only from events before the signal day; exclude the focal stock."""
    dates = list(close.index)
    positions = {day: i for i, day in enumerate(dates)}
    changes = close.pct_change(fill_method=None)
    five_day = close / close.shift(5) - 1
    market_return = changes.median(axis=1)
    market_breadth = (changes > 0).sum(axis=1) / changes.notna().sum(axis=1)
    by_day = defaultdict(list)
    for row in events:
        if row['day'] in positions:
            by_day[row['day']].append(row)
    daily_counts = {day: Counter(r['primaryTheme'] for r in rows if r.get('primaryTheme'))
                    for day, rows in by_day.items()}
    event_cursor, memberships, out = 0, {}, []
    sorted_events = sorted(events, key=lambda r: r['day'])
    for item in sorted(candidates, key=lambda r: (r['signal_date'], r['code'])):
        day, code, theme = item['signal_date'], item['code'], item['theme']
        idx = positions[day]
        while event_cursor < len(sorted_events) and sorted_events[event_cursor]['day'] < day:
            event = sorted_events[event_cursor]
            if event['day'] in positions:
                memberships[event['code']] = (event['primaryTheme'], positions[event['day']])
            event_cursor += 1
        peers = [c for c, (g, i) in memberships.items()
                 if g == theme and i >= idx - 20 and c != code and c in close.columns]
        if theme in GENERIC_EVENT_LABELS:
            peers = []
        peer_today = changes.loc[day, peers].dropna()
        peer_five = five_day.loc[day, peers].dropna()
        peer_return = float(peer_today.median() * 100) if len(peer_today) >= 3 else None
        peer_breadth = float((peer_today > 0).mean()) if len(peer_today) >= 3 else None
        excess_five = float((five_day.at[day, code] - peer_five.median()) * 100) if len(peer_five) >= 3 else None
        counts = daily_counts.get(day, Counter())
        anchor_counts = daily_counts.get(item['anchor_date'], Counter())
        # Subtract this stock's own anchor so it cannot manufacture sector resonance.
        other_anchor_limits = max(0, anchor_counts[theme] - 1)
        top_theme_count = max(counts.values(), default=0)
        market_day = float(market_return.loc[day] * 100)
        structure = {**item, 'peers': peers, 'peer_count': len(peer_today),
                     'peer_return_pct': peer_return, 'peer_breadth': peer_breadth,
                     'excess_five_day_pct': excess_five, 'market_return_pct': market_day,
                     'market_breadth': float(market_breadth.loc[day]),
                     'theme_limitups_today': counts[theme], 'other_anchor_limitups': other_anchor_limits,
                     'theme_limitup_share': counts[theme] / sum(counts.values()) if counts else 0,
                     'theme_count_rank_fraction': sum(v >= counts[theme] for v in counts.values()) / len(counts) if counts else 1}
        structure['resonance'] = bool(other_anchor_limits >= 2 and peer_return is not None
                                      and peer_return > max(0, market_day) and peer_breadth >= .6
                                      and counts[theme] >= 2
                                      and (counts[theme] >= top_theme_count / 2 or structure['theme_count_rank_fraction'] <= .25))
        structure['independent'] = bool(peer_return is not None and peer_return <= 0
                                        and excess_five is not None and excess_five >= 5
                                        and item['daily_return_pct'] - peer_return >= 3)
        out.append(structure)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--events', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    events = read_events(args.events, 'train') + read_events(args.events, 'validation')
    db = sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)
    dates = [r[0] for r in db.execute('SELECT trade_date FROM trading_calendar ORDER BY trade_date')]
    universe = db.execute("SELECT code,name,list_date FROM instruments WHERE instrument_type='STOCK' "
                          "AND (code LIKE '60%' OR code LIKE '00%' OR code LIKE '30%') AND upper(name) NOT LIKE '%ST%' "
                          "AND name NOT LIKE '%退%' ORDER BY code").fetchall()
    by_code = defaultdict(list)
    for row in events:
        by_code[row['code']].append(row)
    close, frames, candidates = {}, {}, []
    for n, (code, name, listed) in enumerate(universe):
        frame = load_frame(db, code, dates)
        close[code] = frame.close * frame.factor
        if code in by_code:
            rows = stock_candidates(frame, by_code[code], listed)
            if rows:
                frames[code] = frame
                candidates.extend(rows)
        if n % 600 == 0:
            print('prepared', n, '/', len(universe), flush=True)
    candidates = add_theme_evidence(candidates, events, pd.DataFrame(close))
    candidates = [r for r in candidates if '02-01' <= r['signal_date'][5:] <= '08-31']
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'candidates.json').write_text(json.dumps(candidates, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    # Freeze just the prices execution needs, retaining float64 precision.
    codes = sorted(frames)
    arrays = {field: np.column_stack([frames[c][field].to_numpy(dtype=float) for c in codes])
              for field in ('open', 'high', 'low', 'close', 'volume', 'factor')}
    np.savez_compressed(args.output / 'execution.npz', dates=np.array(dates), codes=np.array(codes), **arrays)
    required = sorted({r['signal_date'] for r in candidates
                       if '02-01' <= r['signal_date'][5:] <= '08-31'
                       and (r['peer_return_pct'] or 0) > 0 and (r['peer_breadth'] or 0) >= .5
                       and r['market_breadth'] >= .35})
    (args.output / 'fund_dates.json').write_text(json.dumps(required), encoding='utf-8')
    print(json.dumps({'events': len(events), 'candidates': len(candidates), 'codes': len(codes),
                      'resonance': sum(r['resonance'] for r in candidates),
                      'independent': sum(r['independent'] for r in candidates), 'fund_dates': len(required)}), flush=True)


if __name__ == '__main__':
    main()
