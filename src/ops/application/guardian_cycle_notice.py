"""User-facing facts for an intraday Guardian cycle."""
from __future__ import annotations

import secrets
from collections.abc import Sequence


def observation_changes(before: dict, after: dict, at: str, *, references: Sequence[dict] = ()) -> list[dict[str, str]]:
    previous = {item['code']: item for item in before.get('watchlist', [])}
    current = {item['code']: item for item in after.get('watchlist', [])}
    visible_references = {item['code']: item for item in references}
    dismissed_before = before.get('reference_dismissals', {})
    dismissed_after = after.get('reference_dismissals', {})
    changes = []
    for code in sorted(previous.keys() | current.keys() | visible_references.keys()):
        old, new = previous.get(code), current.get(code)
        if old is None:
            if new is not None:
                action = 'watch'
            elif code in visible_references and dismissed_before.get(code) != dismissed_after.get(code):
                action = 'unwatch'
            else:
                continue
        elif new is None:
            action = 'unwatch'
        elif any(old.get(key) != new.get(key) for key in ('entry_condition', 'exit_condition')):
            action = 'update'
        else:
            continue
        item = new or old or visible_references[code]
        changes.append({'action': action, 'code': code, 'name': item.get('name') or code,
                        'at': new.get('added_at', at) if action == 'watch' else at})
    return changes


def observation_notice(changes: list[dict[str, str]]) -> str:
    labels = {'watch': '移入观察', 'unwatch': '移出观察', 'update': '更新观察条件'}
    return '\n'.join(f"{labels[item['action']]} · {item['name']} {item['code']} · {item['at'][:16].replace('T', ' ')}"
                     for item in changes)


def publish_cycle_report(slot: str, result: dict) -> str:
    """Publish a small, immutable, read-only report before queuing its notice."""
    from src.ops.application.guardian_report_share import public_report_base_url, publish_document_share
    from src.ops.application.trading_report_content import trading_run_sections

    if not public_report_base_url():
        return ''
    document = {'title': f"{slot[:16].replace('T', ' ')} · 五分钟研判", 'owner': '天才交易员',
                'created_at': result.get('as_of', slot),
                'sections': trading_run_sections(result, status=result.get('status', ''))}
    token = secrets.token_urlsafe(32)
    return publish_document_share(token, {'kind': 'guardian_cycle', 'slot': slot}, document)
