"""Daily report notices describe committed observation changes without reasons."""

from src.ops.application.guardian_review_digest import DIGEST_MAX_BYTES, notification_digest


REPORT_FINISHED = '2026-09-23T16:10:31.617440+08:00'
REPORT_LINK = 'https://qianlong.chenkit.cloud/shared/reports/3U2Oo6lt0YSmPcYW6Z4xz2kQk5XMzkpnhnOtGww78xk'


def test_daily_digest_includes_actual_four_observation_changes_and_report_link():
    facts = {
        'period': 'daily', 'period_pnl_cents': -648,
        'created_at': '2026-09-23T15:59:10+08:00',
        'account': {'equity_cents': 20_596_387, 'cash_cents': 1_281_387,
                    'positions': [{}] * 6},
        'trades': [{}] * 8,
        'stock_names': {'300795': '米奥会展', '600127': '金健米业',
                        '300931': '通用电梯', '600326': '西藏天路'},
        'watchlist': [
            {'code': '300795', 'name': '米奥会展'},
            {'code': '600127', 'name': '金健米业'},
            {'code': '600326', 'name': '西藏天路',
             'entry_condition': '旧箱体条件', 'exit_condition': '旧退出条件'},
        ],
    }
    analysis = {
        'notification_summary': '观察理由应留在报告里。',
        'watchlist_updates': [
            {'code': '300795', 'action': 'unwatch', 'reason': '米奥观察理由'},
            {'code': '600127', 'action': 'unwatch', 'reason': '金健观察理由'},
            {'code': '300931', 'action': 'watch', 'reason': '通用观察理由',
             'entry_condition': '新条件', 'exit_condition': '新失效条件'},
            {'code': '600326', 'action': 'watch', 'reason': '西藏观察理由',
             'entry_condition': '新箱体条件', 'exit_condition': '旧退出条件'},
        ],
    }

    body = notification_digest(facts, analysis, share_url=REPORT_LINK, observed_at=REPORT_FINISHED)

    for line in (
        '移出观察 · 米奥会展 300795 · 2026-09-23 16:10',
        '移出观察 · 金健米业 600127 · 2026-09-23 16:10',
        '移入观察 · 通用电梯 300931 · 2026-09-23 16:10',
        '更新观察条件 · 西藏天路 600326 · 2026-09-23 16:10',
    ):
        assert line in body
    assert REPORT_LINK in body
    assert '15:59' not in body
    assert '观察理由' not in body
    assert '期间盈亏 -6.48元' in body
    assert len(body.encode('utf-8')) <= DIGEST_MAX_BYTES
    assert len(f'【天才交易员 · 日复盘 · 2026-09-23】\n{body}'.encode('utf-8')) <= 2048


def test_digest_does_not_claim_reason_only_watch_refresh_is_a_condition_change():
    facts = {
        'period': 'daily', 'period_pnl_cents': 0,
        'account': {'equity_cents': 20_000_000, 'cash_cents': 20_000_000, 'positions': []},
        'trades': [],
        'watchlist': [{'code': '600326', 'name': '西藏天路',
                       'entry_condition': '原条件', 'exit_condition': '原退出条件'}],
    }
    analysis = {'watchlist_updates': [{'code': '600326', 'action': 'watch', 'reason': '只是更新研究理由',
                                       'entry_condition': '原条件', 'exit_condition': '原退出条件'}]}

    body = notification_digest(facts, analysis, observed_at=REPORT_FINISHED, share_url=REPORT_LINK)

    assert '观察调整' not in body
    assert '只是更新研究理由' not in body
    assert REPORT_LINK in body
