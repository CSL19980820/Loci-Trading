"""Read-only curve and protection diagnostics; never submit orders or alter plans."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.ledger import build_holding_curve, load_guardian_curve_evidence, guardian_available_quantity
from src.ops.application.guardian_risk import evaluate_risk_plans
from src.ops.application.guardian_quotes import quote_error

TZ = ZoneInfo('Asia/Shanghai')


def protection_summary(state: dict, now: datetime) -> list[dict]:
    # Validation runs on a copy with no executable quote, so it cannot generate
    # sell intentions and never changes the user's saved contracts.
    checked, _, events = evaluate_risk_plans(state, {}, now)
    result = []
    for p in checked.get('positions', []):
        plans = [r['contract'] for r in p.get('risk_plans', [])
                 if r.get('status') == 'active' and r.get('contract', {}).get('action') == 'stop_loss']
        try:
            mark_at = datetime.fromisoformat(str(p.get('mark_at', '')))
            mark_at = mark_at.replace(tzinfo=mark_at.tzinfo or TZ).astimezone(TZ)
        except ValueError:
            mark_at = None
        price = p.get('mark_price_cents')
        quote = {'code': p['code'], 'price': price / 100 if type(price) is int and price > 0 else 0,
                 'trade_date': mark_at.strftime('%Y%m%d') if mark_at else '',
                 'trade_time': mark_at.strftime('%H%M%S') if mark_at else ''}
        stale = bool(quote_error(p['code'], quote, now))
        available = guardian_available_quantity(p, now.date().isoformat())
        quantity = p['quantity']
        covered = min(quantity, sum(r['quantity'] for r in plans))
        invalid = [r for r in events if r['code'] == p['code'] and r['status'] in ('expired', 'invalidated')]
        result.append({'code': p['code'], 'name': p['name'], 'quantity': quantity,
                       'available_quantity': available, 'locked_quantity': quantity - available,
                       'protected_quantity': covered, 'unprotected_quantity': quantity - covered,
                       'stale': stale, 'invalid_plans': len(invalid),
                       'stops': [{'price': r['trigger_price'], 'quantity': r['quantity'],
                                  'valid_until': r['execution']['valid_until'],
                                  'reached': not stale and quote['price'] <= r['trigger_price']}
                                 for r in plans]})
    return result


def get_holding_curve(*, code: str = '', days: int = 30, now: datetime | None = None,
                      db_path=None) -> dict:
    now = now or datetime.now(TZ)
    evidence = load_guardian_curve_evidence(days=days, now=now, db_path=db_path)
    curve = build_holding_curve(evidence, code=code, days=days, now=now)
    curve['protection'] = protection_summary(evidence['state'], now)
    return curve
