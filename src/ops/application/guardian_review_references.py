"""策略参考池的确定性覆盖；模型省略不等于策略未选出。"""


def current_references(facts):
    start = facts.get('baseline_date') if facts['period'] == 'premarket' else facts.get('start_date', facts['trade_date'])
    end = facts.get('baseline_date') if facts['period'] == 'premarket' else facts['trade_date']
    rows = []
    for row in facts.get('strategy_reference_pool', []):
        signals = [s for s in row.get('signals', []) if start <= str(s.get('date') or '') <= end]
        if signals:
            rows.append({**row, 'signals': signals})
    return rows


def reference_summary(facts):
    names = {s['slug']: s.get('name', s['slug']) for s in facts.get('active_strategies', [])}
    groups = {slug: [] for slug in names}
    from src.strategy import describe_all
    names = {**{s['slug']: s.get('name', s['slug']) for s in describe_all()}, **names}
    for row in current_references(facts):
        for signal in row['signals']:
            slug = signal.get('strategy_slug') or signal.get('rule_version')
            if not slug:
                slug = row['strategies'][0] if len(row.get('strategies', [])) == 1 else '来源待核对'
            entry = f"{row['name']}（{row['code']}，{signal['date']}）"
            if entry not in groups.setdefault(slug, []):
                groups[slug].append(entry)
    return [f"{names.get(slug, slug)}：" + ('、'.join(rows) if rows else '本期参考快照未包含精选结果；不据此断言选股任务已成功或确为零命中。') for slug, rows in groups.items()]
