"""Cash-flow-neutral holding curves from recorded valuations and executed fills only."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')


def stamp(value: Any) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(value))
        return value.replace(tzinfo=value.tzinfo or TZ).astimezone(TZ)
    except (TypeError, ValueError):
        return None


def curve_snapshot(state: dict | None) -> dict | None:
    """Small financial evidence; no prompts, plans or model conclusions."""
    if not isinstance(state, dict) or state.get('account_version') != 2:
        return None
    keys = ('account_version', 'initial_capital_cents', 'cash_cents', 'equity_cents',
            'realized_pnl_cents', 'fees_cents', 'stale_codes', 'valuation_at',
            'valuation_kind', 'valuation_date')
    result = {k: state[k] for k in keys if k in state}
    if isinstance(state.get('positions'), list):
        result['positions'] = [{k: p[k] for k in ('code', 'name', 'quantity', 'cost_cents',
            'mark_price_cents', 'mark_at', 'mark_source', 'valuation_stale') if k in p}
            for p in state['positions']]
    return result


def _integer(row: dict, key: str, minimum: int | None = None) -> int:
    value = row.get(key)
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError(f'账本字段 {key} 无效，曲线已停止计算')
    return value


def _fresh(p: dict, at: datetime, account: dict) -> bool:
    if type(p.get('mark_price_cents')) is not int or p['mark_price_cents'] <= 0:
        return False
    quote_at = stamp(p.get('mark_at'))
    if quote_at is None or quote_at > at or not p.get('mark_source'):
        return False
    if account.get('valuation_kind') == 'official_close' and account.get('valuation_date') == quote_at.date().isoformat():
        return True
    return (at - quote_at).total_seconds() <= 180 and not p.get('valuation_stale', False)


def _summary(points: list[dict]) -> dict:
    peak = None
    peak_at = None
    deepest = 0.0
    deepest_peak = deepest_at = None
    valid = 0
    for point in points:
        value = point.get('nav')
        point['drawdown_pct'] = None
        if value is None:
            continue
        valid += 1
        if peak is None or value > peak:
            peak, peak_at = value, point['at']
        dd = min(0.0, (value / peak - 1) * 100) if peak and peak > 0 else None
        point['drawdown_pct'] = round(dd, 6) if dd is not None else None
        if dd is not None and dd < deepest:
            deepest, deepest_peak, deepest_at = dd, peak_at, point['at']
    last = points[-1] if points else {}
    last_valid = next((p for p in reversed(points) if p.get('nav') is not None), {})
    return {'current_drawdown_pct': last.get('drawdown_pct'),
            'last_valid_drawdown_pct': last_valid.get('drawdown_pct'),
            'last_valid_at': last_valid.get('at'),
            'last_valid_pnl_cents': last_valid.get('pnl_cents'),
            'max_drawdown_pct': round(deepest, 6) if valid >= 2 else None,
            'peak_at': peak_at, 'max_drawdown_peak_at': deepest_peak,
            'max_drawdown_at': deepest_at, 'valid_points': valid,
            'latest_nav': last.get('nav'), 'latest_pnl_cents': last.get('pnl_cents'),
            'recovery_pct': round((peak / last['nav'] - 1) * 100, 6)
                if peak and last.get('nav') and last['nav'] > 0 else None}


def build_holding_curve(evidence: dict, *, code: str = '', days: int = 30,
                        now: datetime | None = None) -> dict:
    now = now or datetime.now(TZ)
    now = now.replace(tzinfo=now.tzinfo or TZ).astimezone(TZ)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    current = evidence['state']
    initial = _integer(current, 'initial_capital_cents', 1)
    fills = sorted(evidence['trades'], key=lambda f: (stamp(f['occurred_at']) or datetime.min.replace(tzinfo=TZ), f.get('id', '')))
    position = next((p for p in current.get('positions', []) if p['code'] == code), None) if code else None
    if code and position is None:
        raise LookupError('该股票已不在当前持仓中，请刷新持仓列表')
    episode = None
    if code:
        for fill in fills:
            if fill['code'] == code and fill.get('side') == 'buy' and fill.get('before_quantity') == 0:
                episode = stamp(fill['occurred_at'])
        if episode is None:
            raise ValueError('当前持仓缺少开仓成交，不能补造持仓曲线')
    snapshots = list(evidence['snapshots'])
    snapshots.append({'state': curve_snapshot(current), 'source': 'current', 'current': True})
    events: list[tuple[datetime, int, str, dict]] = []
    for fill in fills:
        at = stamp(fill.get('occurred_at'))
        if at is None or at > now:
            raise ValueError('成交流水时间无效或来自未来')
        events.append((at, 0, fill.get('id', ''), fill))
    for n, item in enumerate(snapshots):
        snap = item.get('state')
        if not snap:
            continue
        at = stamp(snap.get('valuation_at'))
        if at and at <= now:
            events.append((at, 1, str(n).zfill(8), item))
    events.sort(key=lambda e: e[:3])
    cash, realized, fees = initial, 0, 0
    quantities: dict[str, int] = {}
    costs: dict[str, int] = {}
    stock_nav, last_price = Decimal(1), None
    stock_in, stock_out = 0, 0
    points: list[dict] = []
    excluded = 0
    first_trade = stamp(fills[0]['occurred_at']) if fills else None
    baseline = episode if code else first_trade
    if baseline and baseline >= start:
        points.append({'at': (baseline - timedelta(microseconds=1)).isoformat(), 'nav': 1.0,
                       'pnl_cents': 0, 'equity_cents': None if code else initial,
                       'kind': 'baseline', 'quantity': 0, 'quality': 'verified'})
    for at, event_type, _, row in events:
        if event_type == 0:
            c, side = row['code'], row['side']
            if side not in ('buy', 'sell'):
                raise ValueError('成交方向无效')
            q, gross, fee, px = (_integer(row, k, 1 if k in ('quantity', 'price_cents') else 0)
                                  for k in ('quantity', 'gross_cents', 'fees_cents', 'price_cents'))
            before = quantities.get(c, 0)
            if before != _integer(row, 'before_quantity', 0) or gross != q * px:
                raise ValueError('成交流水股数或金额无法核对')
            after = before + (q if side == 'buy' else -q)
            if after < 0 or after != _integer(row, 'after_quantity', 0):
                raise ValueError('成交流水余额无法核对')
            allocated = _integer(row, 'allocated_cost_cents', 0)
            trade_realized = _integer(row, 'realized_pnl_cents')
            if side == 'sell' and (allocated > costs.get(c, 0) or trade_realized != gross - fee - allocated):
                raise ValueError('卖出成本或已实现盈亏无法核对')
            cash += gross - fee if side == 'sell' else -gross - fee
            realized += trade_realized
            fees += fee
            costs[c] = costs.get(c, 0) + (gross + fee if side == 'buy' else -allocated)
            quantities[c] = after
            if cash != _integer(row, 'cash_after_cents', 0) or cash + sum(costs.values()) != initial + realized:
                raise ValueError('账户现金与成交流水对账不平')
            if not code or c != code or at < episode:
                continue
            # Revalue existing units at execution price before adding/redeeming
            # capital. Price changes and fees, not changing share counts, move NAV.
            if before and last_price:
                stock_nav *= Decimal(px) / Decimal(last_price)
            if side == 'buy':
                pre = before * px
                stock_nav *= Decimal(pre + gross) / Decimal(pre + gross + fee)
                stock_in += gross + fee
            else:
                stock_nav *= Decimal(before * px - fee) / Decimal(before * px)
                stock_out += gross - fee
            last_price = px
            point = {'at': at.isoformat(), 'nav': float(stock_nav),
                     'pnl_cents': after * px + stock_out - stock_in,
                     'quantity': after, 'price_cents': px, 'market_value_cents': after * px,
                     'kind': side, 'trade_quantity': q, 'fees_cents': fee,
                     'source': 'executed_fill', 'quote_at': row.get('quote_at'), 'quality': 'verified'}
        else:
            snap = row['state']
            check_at = at
            if code and at < episode:
                continue
            valid = snap.get('initial_capital_cents') == initial and snap.get('cash_cents') == cash
            if snap.get('realized_pnl_cents') != realized or snap.get('fees_cents') != fees:
                valid = False
            if code:
                p = next((p for p in snap.get('positions', []) if p.get('code') == code), None)
                if p is None:
                    continue
                valid = valid and p.get('quantity') == quantities.get(code, 0) and p.get('cost_cents') == costs.get(code, 0)
                valid = valid and _fresh(p, check_at, snap)
                px = p.get('mark_price_cents')
                if valid and last_price and quantities.get(code):
                    stock_nav *= Decimal(px) / Decimal(last_price)
                    last_price = px
                else:
                    valid = False
                point = {'at': at.isoformat(), 'nav': float(stock_nav) if valid else None,
                         'pnl_cents': quantities[code] * px + stock_out - stock_in if valid else None,
                         'quantity': quantities.get(code, 0),
                         'price_cents': px if type(px) is int and px > 0 else None,
                         'market_value_cents': quantities[code] * px if valid else None,
                         'quote_at': p.get('mark_at'), 'source': p.get('mark_source')}
            else:
                equity = snap.get('equity_cents')
                valid = valid and type(equity) is int and equity >= 0
                valid = valid and snap.get('stale_codes') == []
                if isinstance(snap.get('positions'), list):
                    valid = valid and {p['code']: p['quantity'] for p in snap['positions']} == {c: q for c, q in quantities.items() if q}
                    valid = valid and all(_fresh(p, check_at, snap) for p in snap['positions'])
                    if valid:
                        valid = cash + sum(p['quantity'] * p['mark_price_cents'] for p in snap['positions']) == equity
                point = {'at': at.isoformat(), 'nav': equity / initial if valid else None,
                         'pnl_cents': equity - initial if valid else None,
                         'equity_cents': equity if valid else None, 'cash_cents': cash,
                         'source': row.get('source', 'recorded_account')}
            point.update(kind='valuation', quality='verified' if valid else 'unavailable')
            if not valid:
                excluded += int(at >= start)
        if at >= start:
            points.append(point)
    if (cash != current.get('cash_cents') or fees != current.get('fees_cents')
            or realized != current.get('realized_pnl_cents')
            or {c: q for c, q in quantities.items() if q} != {p['code']: p['quantity'] for p in current.get('positions', [])}
            or any(costs[p['code']] != p['cost_cents'] for p in current.get('positions', []))):
        raise ValueError('当前账户与成交流水不一致，暂停展示曲线并请核对账本')
    deduped: dict[tuple[str, str], dict] = {}
    for p in points:
        deduped[(p['at'], p['kind'])] = p
    points = sorted(deduped.values(), key=lambda p: (stamp(p['at']), p['kind'] != 'baseline', p['kind'] == 'valuation'))
    held = [position] if position else current.get('positions', [])
    if held and any(not _fresh(p, now, current) for p in held):
        points.append({'at': now.isoformat(), 'nav': None, 'pnl_cents': None,
                       'kind': 'unavailable', 'quality': 'unavailable', 'source': 'quote_not_current'})
    elif not points and not held:
        points.append({'at': now.isoformat(), 'nav': cash / initial, 'pnl_cents': cash - initial,
                       'equity_cents': cash, 'kind': 'valuation', 'quality': 'verified'})
    summary = _summary(points)
    return {'code': code, 'name': position['name'] if position else '账户净值',
            'scope': 'holding' if code else 'account', 'as_of': now.isoformat(),
            'start': start.date().isoformat(), 'end': now.date().isoformat(),
            'opened_at': episode.isoformat() if episode else None,
            'points': points, 'summary': summary, 'excluded_points': excluded,
            'coverage': {**evidence.get('coverage', {}), 'sampled': True},
            'method': 'holding_unit_nav_net_fees_v1' if code else 'account_equity_v1'}
