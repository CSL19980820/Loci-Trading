"""Run with: python -m cli.migrate_report_shares --data-root <LOCI_DATA_DIR>.

Default: read-only inventory. --apply indexes recoverable existing links.
Only --apply --remove-html removes old files after exact-version resolution succeeds.
No model calls, notification delivery, account writes or server restart.
"""
import argparse
import json
from pathlib import Path

from src.ops.application.report_share_migration import migrate_report_shares


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True, type=Path, help='Explicit active LOCI_DATA_DIR; never guessed')
    parser.add_argument('--primary-db', type=Path, help='Explicit PALACE_DB override, when outside data-root')
    parser.add_argument('--apply', action='store_true', help='Write the lightweight public share index')
    parser.add_argument('--remove-html', action='store_true', help='Remove only verified legacy HTML; requires --apply')
    args = parser.parse_args()
    if args.remove_html and not args.apply:
        parser.error('--remove-html requires --apply')
    result = migrate_report_shares(args.data_root, apply=args.apply, remove_html=args.remove_html,
                                   primary_db=args.primary_db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result['errors'] or result['unresolved'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
