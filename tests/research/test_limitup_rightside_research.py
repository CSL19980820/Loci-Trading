"""Behavioral checks for right-side confirmation, historical peers and risk sizing."""
import json

import numpy as np
import pandas as pd
import pytest

from scripts.high_payoff_research import account
from scripts.limitup_rightside_features import add_theme_evidence, stock_candidates
from scripts.limitup_rightside_research import attach_funds, matches


def setup_pattern():
    dates = pd.bdate_range('2026-02-02', periods=30).strftime('%Y-%m-%d').tolist()
    frame = pd.DataFrame({'open': 10., 'high': 10.1, 'low': 9.9, 'close': 10.,
                          'volume': 10_000_000., 'factor': 1.}, index=dates)
    for idx, values in {
        20: [10., 11., 9.95, 11., 100_000_000.],
        21: [11., 11.2, 10.9, 11.1, 70_000_000.],
        22: [11., 11.05, 10.6, 10.8, 40_000_000.],
        23: [10.8, 10.9, 10.5, 10.7, 30_000_000.],
        24: [10.75, 11.18, 10.7, 11.15, 60_000_000.],
    }.items():
        frame.loc[dates[idx], ['open', 'high', 'low', 'close', 'volume']] = values
    event = {'day': dates[20], 'code': '600001', 'name': 'fixture', 'continueNum': 1,
             'tradingAmount': 1_000_000_000, 'primaryTheme': 'test-theme', 'limitUpType': '换手板', 'latest': 11.}
    return frame, event, dates


def test_requires_confirmation_after_two_completed_pullback_bars():
    frame, event, dates = setup_pattern()
    found = stock_candidates(frame, [event], '2000-01-01')
    assert len(found) == 1
    assert found[0]['signal_date'] == dates[24]
    assert found[0]['anchor_date'] == dates[20]
    assert found[0]['pullback_days'] == 2
    assert found[0]['stop_level'] < 10.5
    assert not stock_candidates(frame.loc[:dates[23]], [event], '2000-01-01')


def test_future_prices_and_future_anchor_cannot_change_past_confirmation():
    frame, event, dates = setup_pattern()
    expected = stock_candidates(frame.loc[:dates[24]], [event], '2000-01-01')
    assert len(expected) == 1
    frame.loc[dates[25]:, ['open', 'high', 'low', 'close']] *= 100
    future_event = {**event, 'day': dates[26], 'primaryTheme': 'future-theme'}
    actual = stock_candidates(frame, [event, future_event], '2000-01-01')
    assert [r for r in actual if r['signal_date'] <= dates[24]] == expected


def test_shrinking_volume_and_rebreak_are_both_required():
    frame, event, dates = setup_pattern()
    frame.loc[dates[22]:dates[23], 'volume'] = 150_000_000
    assert not stock_candidates(frame, [event], '2000-01-01')
    frame, event, dates = setup_pattern()
    frame.loc[dates[24], 'close'] = 10.9
    assert not stock_candidates(frame, [event], '2000-01-01')


def test_mismatched_event_price_cannot_create_limitup_anchor():
    frame, event, _ = setup_pattern()
    event['latest'] = 20.
    assert not stock_candidates(frame, [event], '2000-01-01')


def test_generic_announcements_are_not_a_sector():
    frame, event, _ = setup_pattern()
    event['primaryTheme'] = '公告'
    candidate = stock_candidates(frame, [event], '2000-01-01')[0]
    close = pd.DataFrame({code: frame.close for code in ['600001', '600002', '600003', '600004']})
    events = [{**event, 'code': code} for code in close.columns]
    result = add_theme_evidence([candidate], events, close)[0]
    assert result['peer_count'] == 0
    assert not result['resonance'] and not result['independent']


def test_sector_comparison_excludes_self_and_same_day_new_members():
    frame, event, dates = setup_pattern()
    candidate = stock_candidates(frame, [event], '2000-01-01')[0]
    close = pd.DataFrame({'600001': frame.close, '600002': np.linspace(12, 10, 30),
                          '600003': np.linspace(12, 10, 30), '600004': np.linspace(12, 10, 30),
                          '600005': np.linspace(5, 15, 30)}, index=dates)
    events = [{**event, 'code': code} for code in ('600001', '600002', '600003', '600004')]
    events.append({**event, 'day': dates[24], 'code': '600005'})
    result = add_theme_evidence([candidate], events, close)[0]
    assert set(result['peers']) == {'600002', '600003', '600004'}
    assert result['peer_count'] == 3
    assert result['independent']
    assert not result['resonance']


def test_risk_budget_and_theme_cap_apply_before_using_trade_outcomes():
    dates = ['2026-02-02', '2026-02-03', '2026-02-04']
    codes = ['600001', '600002']
    choices = {dates[0]: [{'code': c, 'name': c, 'theme': 'same', 'score': 1} for c in codes]}
    events = {(dates[0], c): {'code': c, 'signal_date': dates[0], 'entry_date': dates[1],
                             'exit_date': dates[2], 'exit_reason': 'data_end',
                             'risk_pct': 6., 'gross_return_pct': 1000.} for c in codes}
    marks = {c: pd.Series(10., index=dates) for c in codes}
    raw = {(dates[1], c): 10. for c in codes}
    factors = {(dates[1], c): 1. for c in codes}
    result = account(choices, events, marks, raw, factors, dates,
                     max_positions=3, slot_capital=40_000, risk_budget=1000, max_per_theme=1)
    assert len(result['open_positions']) == 1
    assert result['open_positions'][0]['quantity'] == 1600
    assert result['open_positions'][0]['notional'] * .06 <= 1000
    assert result['skipped']['theme_capacity'] == 1
    assert result['metrics']['ending_equity'] < 200000


def test_fund_gate_requires_both_dated_money_and_price_confirmation(tmp_path):
    candidate = {'signal_date': '2026-02-03', 'theme': 'test-theme', 'peer_return_pct': 1.,
                 'peer_breadth': .7, 'market_breadth': .6, 'resonance': True, 'independent': False}
    path = tmp_path / '2026-02-03.json'
    document = {'request': {'tradeDate': '2026-02-03'}, 'data': {
        'actualTradeDate': '20260203', 'rows': [
            {'themeName': 'test-theme', 'mainNetAmount': 100000000., 'pctChg': -2.}]}}
    path.write_text(json.dumps(document), encoding='utf-8')
    row = attach_funds([candidate], tmp_path)[0]
    assert row['fund_day_available'] and row['fund_theme_exact_match']
    assert not matches(row, 'fund_resonance')
    document['data']['rows'][0]['pctChg'] = 2.
    path.write_text(json.dumps(document), encoding='utf-8')
    assert matches(attach_funds([candidate], tmp_path)[0], 'fund_resonance')
    document['data']['actualTradeDate'] = '20260204'
    path.write_text(json.dumps(document), encoding='utf-8')
    with pytest.raises(ValueError, match='Date mismatch'):
        attach_funds([candidate], tmp_path)
