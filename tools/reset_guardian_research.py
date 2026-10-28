"""预览或备份后重置指定租户的交易员研究上下文，不删除审计历史。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--reset-id', required=True)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    path = args.db.resolve(strict=True)
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as source:
        row = source.execute('SELECT state_json FROM guardian_portfolio WHERE id=1').fetchone()
        state = json.loads(row[0])
        preview = {'db': str(path), 'previous_reset_at': state.get('research_reset_at'),
                   'watchlist': len(state.get('watchlist', [])), 'positions': len(state['positions']),
                   'preserved_trades': source.execute('SELECT count(*) FROM guardian_trades').fetchone()[0],
                   'archived_reports': source.execute('SELECT count(*) FROM guardian_reports').fetchone()[0],
                   'experience_versions': source.execute('SELECT count(*) FROM guardian_experience_versions').fetchone()[0]}
        if not args.apply:
            print(json.dumps({'preview': preview}, ensure_ascii=False))
            return
        if not args.backup:
            parser.error('--apply 必须提供 --backup')
        backup = args.backup.resolve()
        if backup == path or backup.exists():
            parser.error('备份路径必须是不同于原库的新文件')
        backup.parent.mkdir(parents=True, exist_ok=True)
        with backup.open('xb'):
            pass
        with sqlite3.connect(backup) as destination:
            source.backup(destination)
    from src.ledger import GuardianStore
    with GuardianStore(path) as ledger:
        result = ledger.reset_research_context(args.reset_id)
    print(json.dumps({'preview': preview, 'backup': str(backup), 'result': result}, ensure_ascii=False))


if __name__ == '__main__':
    main()
