"""Execute frozen right-side signals through the existing Loci matching engine."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.high_payoff_research import PERIODS, account
from src.backtest import BacktestConfig, run_backtest


ROUTES = ('structure_control', 'theme_resonance', 'independent_leader', 'fund_coverage_control', 'fund_resonance')


def attach_funds(candidates: list[dict], folder: Path) -> list[dict]:
    by_day = {}
    for path in sorted(folder.glob('*.json')):
        block = json.loads(path.read_text(encoding='utf-8'))
        data = block.get('data', {})
        requested = block['request']['tradeDate'].replace('-', '')
        actual = str(data.get('actualTradeDate') or data.get('tradeDate') or '').replace('-', '')
        if requested != actual or data.get('dateStatus') == 'mismatch':
            raise ValueError(f'Date mismatch in {path}')
        by_day[pd.Timestamp(requested).strftime('%Y-%m-%d')] = data
    rows = []
    for candidate in candidates:
        day_data = by_day.get(candidate['signal_date'], {})
        ranking = day_data.get('rows', [])[:20]
        found = next(((i, row) for i, row in enumerate(ranking, 1)
                      if row.get('themeName') == candidate['theme']), None)
        needed = (candidate['peer_return_pct'] or 0) > 0 and (candidate['peer_breadth'] or 0) >= .5 and candidate['market_breadth'] >= .35
        item = {**candidate, 'fund_lookup_required': needed, 'fund_day_available': bool(ranking),
                'fund_theme_exact_match': found is not None, 'fund_confirmed': False}
        if found:
            rank, row = found
            net = row.get('mainNetAmount')
            item.update({'fund_rank': rank, 'fund_main_net': net,
                         'fund_sector_return_pct': row.get('pctChg'),
                         'fund_snapshot_time': day_data.get('snapshotTime'),
                         'fund_confirmed': rank <= 20 and net is not None and net > 0
                         and (row.get('pctChg') or 0) > 0})
        rows.append(item)
    return rows


def matches(candidate: dict, route: str) -> bool:
    return {
        'structure_control': True,
        'theme_resonance': candidate['resonance'],
        'independent_leader': candidate['independent'],
        'fund_coverage_control': candidate['fund_lookup_required'] and candidate['fund_day_available'],
        'fund_resonance': candidate['fund_confirmed']
        and (candidate['peer_return_pct'] or 0) > 0
        and (candidate['peer_breadth'] or 0) >= .5,
    }[route]


def simulate_events(payload: dict, candidates: list[dict], phase: str, hold: int) -> tuple:
    dates = payload['dates'].tolist()
    code_columns = {code: col for col, code in enumerate(payload['codes'].tolist())}
    date_rows = {day: row for row, day in enumerate(dates)}
    start, end = PERIODS[phase]
    phase_dates = [day for day in dates if start <= day <= end]
    last = date_rows[phase_dates[-1]]
    events, marks, raw, factors, skips = {}, {}, {}, {}, Counter()
    for item in candidates:
        day, code = item['signal_date'], item['code']
        if not start <= day <= end:
            continue
        row, col = date_rows[day], code_columns[code]
        if row + 1 > last:
            skips['end_without_entry'] += 1
            continue
        entry = float(payload['open'][row + 1, col] * payload['factor'][row + 1, col])
        previous = float(payload['close'][row, col] * payload['factor'][row, col])
        risk_pct = (1 - item['stop_level'] / entry) * 100 if entry > 0 else float('nan')
        if not np.isfinite(entry) or not np.isfinite(risk_pct) or not 1.5 <= risk_pct <= 6:
            skips['structural_risk_outside_1.5_6'] += 1
            continue
        if entry / previous - 1 > .03 or entry <= item['stop_level']:
            skips['gap_or_support_failed'] += 1
            continue
        # Include the preceding day to preserve the directional one-price-board check.
        window = slice(row, last + 1)
        days = dates[row:last + 1]
        signals = pd.DataFrame(False, index=days, columns=[code])
        signals.iloc[0, 0] = True
        panels = {field: pd.DataFrame({code: payload[field][window, col] * payload['factor'][window, col]}, index=days)
                  for field in ('open', 'high', 'low', 'close')}
        panels['volume'] = pd.DataFrame({code: payload['volume'][window, col]}, index=days)
        cfg = BacktestConfig(hold_days=hold, stop_loss_pct=-risk_pct,
                             take_profit_pct=2.5 * risk_pct, commission_bps=3.1,
                             stamp_duty_bps=5, slippage_bps=5, benchmark=None)
        result = run_backtest(signals, panels, entry_timing='next_open', config=cfg)
        skips.update(result.skipped)
        if result.skipped.get('持有期内始终无法卖出'):
            raise ValueError('Cannot omit a purchased stock that cannot be sold')
        for trade in result.trades:
            events[(day, code)] = {**asdict(trade), 'risk_pct': risk_pct,
                                   'anchor_date': item['anchor_date'], 'stop_level': item['stop_level']}
            raw[(trade.entry_date, code)] = float(payload['open'][row + 1, col])
            factors[(trade.entry_date, code)] = float(payload['factor'][row + 1, col])
        if code not in marks:
            marks[code] = pd.Series(payload['close'][:, col] * payload['factor'][:, col], index=dates).ffill()
    return events, marks, raw, factors, phase_dates, dict(skips)


def run(root: Path) -> dict:
    candidates = attach_funds(json.loads((root / 'prepared/candidates.json').read_text(encoding='utf-8')), root / 'fund-pages')
    payload = dict(np.load(root / 'prepared/execution.npz', allow_pickle=False))
    results, selection = {}, None
    for phase in PERIODS:
        for hold in (5, 10):
            data = simulate_events(payload, candidates, phase, hold)
            for route in ROUTES:
                choices = defaultdict(list)
                start, end = PERIODS[phase]
                for item in candidates:
                    if start <= item['signal_date'] <= end and matches(item, route):
                        # Equity-wide risk-off filter is shared with the control arm.
                        if item['market_breadth'] < .35:
                            continue
                        choices[item['signal_date']].append({**item, 'score': item['excess_five_day_pct']
                                                            if item['excess_five_day_pct'] is not None else item['daily_return_pct']})
                for rows in choices.values():
                    rows.sort(key=lambda r: (-r['score'], -r['anchor_amount'], r['code']))
                    del rows[3:]
                for stress in (1, 2):
                    key = f'{phase}/{route}/hold{hold}/cost{stress}'
                    output = account(choices, *data[:4], data[4], cost_multiplier=stress,
                                     max_positions=3, slot_capital=40_000, risk_budget=1_000, max_per_theme=2)
                    output['execution_skipped_all_structure_events'] = data[5]
                    output['signals_before_execution'] = sum(len(rows) for rows in choices.values())
                    # Do not label absent historical fund observations as a losing strategy.
                    if route == 'fund_resonance' and not any(r['fund_day_available'] for r in candidates
                                                            if start <= r['signal_date'] <= end):
                        output['status'] = 'missing_historical_funds'
                    else:
                        output['status'] = 'computed_retrospective'
                    results[key] = output
                print(phase, route, hold, json.dumps(results[f'{phase}/{route}/hold{hold}/cost1']['metrics']), flush=True)
        if phase == 'train':
            qualified = []
            for key, output in results.items():
                m = output['metrics']
                if (key.endswith('/cost1') and key.split('/')[1] in ('theme_resonance', 'independent_leader', 'fund_resonance')
                        and m['trades'] >= 20 and (m['payoff_ratio'] or 0) >= 2
                        and (m['profit_factor'] or 0) >= 1.2 and m['return_pct'] > 0
                        and m['max_drawdown_pct'] >= -12
                        and results[key.replace('/cost1', '/cost2')]['metrics']['return_pct'] > 0):
                    qualified.append(key)
            selection = max(qualified, key=lambda key: results[key]['metrics']['profit_factor']) if qualified else None
            (root / 'selection-before-validation.json').write_text(json.dumps({
                'selected': selection, 'qualified': qualified,
                'training_metrics': {key: value['metrics'] for key, value in results.items()}
            }, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    summary = {'periods': PERIODS, 'results': results,
               'selected_on_training': selection,
               'fund_coverage': {year: {'candidates': sum(r['signal_date'].startswith(year) for r in candidates),
                   'eligible_for_fund_route': sum(r['signal_date'].startswith(year) and r['fund_lookup_required'] for r in candidates),
                   'eligible_with_fund_day': sum(r['signal_date'].startswith(year) and r['fund_lookup_required'] and r['fund_day_available'] for r in candidates),
                   'dated_fund_available': sum(r['signal_date'].startswith(year) and r['fund_day_available'] for r in candidates),
                   'exact_theme_match': sum(r['signal_date'].startswith(year) and r['fund_theme_exact_match'] for r in candidates),
                   'confirmed': sum(r['signal_date'].startswith(year) and r['fund_confirmed'] for r in candidates)} for year in ('2025', '2026')},
               'capital': {'initial': 200_000, 'max_positions': 3, 'max_position_notional': 40_000,
                           'risk_budget_per_trade_before_cost': 1_000, 'max_per_theme': 2},
               'status': 'exploratory_retrospective_event_labels_and_survivor_universe'}
    (root / 'results.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (root / 'candidates-with-funds.json').write_text(json.dumps(candidates, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    run(p.parse_args().root)
