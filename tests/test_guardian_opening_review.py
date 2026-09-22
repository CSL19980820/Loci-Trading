from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from src.ledger import GuardianStore
from src.ops.application.guardian_decision import GuardianDecision
from src.ops.application.guardian_outcome import execution_window
from src.ops.application.guardian_session import in_review_window, is_opening_review
from src.ops.application.jobs import guardian

TZ = ZoneInfo('Asia/Shanghai')


@pytest.mark.parametrize('clock,review,opening', [
    ('09:24:59', False, False), ('09:25:00', True, True),
    ('09:29:59', True, True), ('09:30:00', True, False),
])
def test_opening_boundaries(clock, review, opening):
    now = datetime.fromisoformat(f'2026-09-21T{clock}').replace(tzinfo=TZ)
    assert in_review_window(now) == review
    assert is_opening_review(now) == opening
    assert is_opening_review(now.astimezone(ZoneInfo('UTC'))) == opening


def test_opening_is_not_a_fill_window():
    before = datetime(2026, 9, 21, 9, 25, tzinfo=TZ)
    regular = before.replace(minute=30)
    assert not execution_window(before, before, 0)
    assert not execution_window(before, regular, 299)
    assert execution_window(regular, regular, 0)
    assert not is_opening_review(before.replace(day=20))


@pytest.mark.parametrize('clock,notify,alert,expected_notice', [
    ('09:25:10', True, '竞价证据显示变化，开盘前核对持仓；价格条件失效则放弃。', True),
    ('09:25:10', True, '', True),
    ('09:25:10', False, '重要竞价变化', False),
    ('09:30:00', True, '不应在盘中重复发竞价提醒', False),
])
def test_opening_alert_saved_without_fills(tmp_path, monkeypatch, clock, notify, alert, expected_notice):
    instant = datetime.fromisoformat(f'2026-09-21T{clock}').replace(tzinfo=TZ)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    path = tmp_path / 'palace.db'
    cfg = {'enabled': True, 'notify': notify, 'model': 'fixture'}
    store = SimpleNamespace(get_run=lambda _: None, guardian_commit_guard=lambda _: nullcontext())
    market = SimpleNamespace(trading_days=lambda **_: ['2026-09-18'])
    context = SimpleNamespace(ops_store=store, palace_db=path, run_id='',
                              market=lambda: nullcontext(market), check_cancelled=lambda: None)
    seen = []

    def decide(_store, _cfg, payload, **_kwargs):
        seen.append(payload)
        orders = [{'code': '600000', 'action': 'buy', 'quantity': 100, 'reason': '开盘重新核验',
                   'execution': {'kind': 'limit', 'max_price': 10, 'valid_until': '2026-09-21T09:30:00+08:00'}}] if clock < '09:30:00' else []
        if clock < '09:30:00':
            orders.append({'code': '600001', 'name': '观察预案', 'action': 'watch', 'reason': '开盘后再判断', 'entry_condition':'核对新行情'})
        return GuardianDecision(summary='等待开盘重新核验', orders=orders), {}

    monkeypatch.setattr(guardian, 'datetime', Clock)
    monkeypatch.setattr(guardian, 'get_config', lambda _: cfg)
    monkeypatch.setattr(guardian, 'calendar_trading_day', lambda _: True)
    monkeypatch.setattr(guardian, 'PalaceStore', MagicMock())
    monkeypatch.setattr(guardian, 'observe', lambda *_: [])
    monkeypatch.setattr(guardian, 'strategy_sources', lambda _: [])
    monkeypatch.setattr(guardian, 'decide', decide)
    monkeypatch.setattr(guardian, 'data_source', lambda: {'label': 'isolated fixture'})
    monkeypatch.setattr(guardian, 'deliver_pending', lambda *_: {})
    result = guardian.execute_guardian({}, context)
    assert result['fills'] == []
    if clock < '09:30:00':
        assert result['deferred'][0]['quantity'] == 100
    assert seen[0]['review_phase'] == ('opening_auction' if clock < '09:30:00' else 'intraday')
    with GuardianStore(path) as ledger:
        assert ledger.trades()['total'] == 0
        assert ledger.state().get('watchlist', []) == []
        notices = list(ledger.conn.execute('SELECT title,body FROM guardian_notices'))
        assert bool(notices) == expected_notice
        if expected_notice:
            assert '09:25操作预案' in notices[0]['title']
            assert '600000' in notices[0]['body']
            assert '600001' in notices[0]['body']
            assert '不挂单、不成交' in notices[0]['body']
            assert '09:30' in notices[0]['body']

