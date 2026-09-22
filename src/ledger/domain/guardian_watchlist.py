"""自主观察修改；移除决定不会被同一批量化候选重新覆盖。"""


def update_watchlist(state: dict, update: dict, at: str, *, name: str = '', source: str = '') -> None:
    code = update['code']
    watched = state.setdefault('watchlist', [])
    existing = next((w for w in watched if w['code'] == code), None)
    if update['action'] == 'unwatch':
        if existing:
            watched.remove(existing)
        state.setdefault('reference_dismissals', {})[code] = {'through_date': at[:10], 'reason': update['reason'], 'at': at}
    elif update['action'] == 'watch':
        state.get('reference_dismissals', {}).pop(code, None)
        entry = {'code': code, 'name': name or (existing or {}).get('name') or code,
                 'reason': update['reason'], 'entry_condition': update.get('entry_condition', ''),
                 'exit_condition': update.get('exit_condition', ''), 'updated_at': at,
                 'added_at': (existing or {}).get('added_at', at), 'source': source}
        if existing:
            existing.update(entry)
        else:
            watched.append(entry)
    else:
        raise ValueError('未知观察名单操作')
