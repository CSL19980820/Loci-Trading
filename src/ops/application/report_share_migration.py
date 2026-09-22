"""将已发布的旧链接登记为动态页面；仅显式确认后清理已核验的 HTML。"""
from contextlib import closing
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3

from src.ops.application.guardian_report_share import (
    guardian_reference, read_shared_report, render_share_descriptor,
)
from src.ops.application.stock_agent_report_share import stock_agent_document, stock_agent_identity
from src.ops.infrastructure.report_share_store import (
    TOKEN_PATTERN, readonly_connection, register_share, reject_symlinks,
)


class _BodyText(HTMLParser):
    def __init__(self, page: str):
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.parts = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        if tag == 'body':
            self.in_body = True

    def handle_endtag(self, tag):
        if tag == 'body':
            self.in_body = False

    def handle_data(self, text):
        if self.in_body:
            self.parts.append(text)

    def normalized(self) -> str:
        return re.sub(r'\s+', '', ''.join(self.parts))


def _saved_publications(db: Path, root: Path, wanted: set[str]):
    """Read existing ledgers only; never generate a token or publish an unshared report."""
    with closing(readonly_connection(db)) as conn:
        conn.execute('BEGIN')
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('guardian_reports', 'guardian_report_revisions'):
            if table not in tables:
                continue
            where = " WHERE status='success'" if table == 'guardian_reports' else ''
            for row in conn.execute(f'SELECT report_key,result_json FROM {table}{where}'):
                result = json.loads(row['result_json'])
                token = result.get('share_token')
                if token not in wanted:
                    continue
                period, day = row['report_key'].split(':', 1)
                reference = guardian_reference(db, period, day, result, root=root)
                yield token, reference, reference
        if {'stock_agent_runs', 'stock_agent_profiles'} <= tables:
            query = '''SELECT r.id,r.agent_id,r.phase,r.started_at,r.finished_at,r.summary,r.detail_json,p.config_json
                FROM stock_agent_runs r JOIN stock_agent_profiles p ON p.id=r.agent_id
                WHERE r.status='success' '''
            for row in conn.execute(query):
                detail = json.loads(row['detail_json'])
                token = detail.get('share_token')
                if token not in wanted:
                    continue
                run = dict(row)
                run['detail'] = detail
                profile = {'config': json.loads(row['config_json'])}
                document = stock_agent_document(profile, run, '')
                if document:
                    identity = stock_agent_identity(db, row['agent_id'], row['id'], run, root=root)
                    yield token, identity, {'version': 1, 'kind': 'document', 'document': document}


def migrate_report_shares(root: Path, *, apply: bool = False, remove_html: bool = False,
                          primary_db: Path | None = None) -> dict:
    """Dry-run by default. The source ledgers and all unknown old links remain unchanged."""
    root = root.absolute()
    reject_symlinks(root)
    if not root.is_dir():
        raise FileNotFoundError('指定的数据根不存在')
    if remove_html and not apply:
        raise ValueError('清理旧 HTML 必须同时显式指定 apply')
    report = {'dry_run': not apply, 'legacy_files': 0, 'verified': 0, 'indexed': 0,
              'removed_html': 0, 'removed_bytes': 0, 'eligible_bytes': 0, 'unresolved': 0, 'errors': []}
    directory = root / 'shared_reports'
    reject_symlinks(directory)
    files = {}
    for path in sorted(directory.glob('*.html')):
        if TOKEN_PATTERN.fullmatch(path.stem):
            reject_symlinks(path)
            if path.is_file():
                files[path.stem] = path
    report['legacy_files'] = len(files)
    if not files:
        return report
    tenants = root / 'tenants'
    reject_symlinks(tenants)
    sources = [primary_db or root / 'palace.db']
    sources.extend(sorted(tenants.glob('*/palace.db')))
    matches, conflicts = {}, set()
    for db in dict.fromkeys(sources):
        try:
            reject_symlinks(db)
            if not db.is_file():
                continue
            for token, identity, descriptor in _saved_publications(db, root, set(files)):
                if token in matches and matches[token][0] != identity:
                    conflicts.add(token)
                else:
                    matches[token] = (identity, descriptor)
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            report['errors'].append({'source': db.name, 'error': type(exc).__name__})
    for token in conflicts:
        matches.pop(token, None)
        report['errors'].append({'link_hash': hashlib.sha256(token.encode()).hexdigest()[:12], 'error': 'token_conflict'})
    for token, (identity, descriptor) in matches.items():
        path = files[token]
        try:
            before = path.stat()
            page = render_share_descriptor(token, descriptor, root=root)
            if not page:
                raise ValueError('报告版本已不存在')
            if descriptor['kind'] == 'document':
                # A renamed/deleted profile or changed source text is not silently substituted.
                old_text = _BodyText(path.read_text(encoding='utf-8')).normalized()
                if not old_text or old_text != _BodyText(page).normalized():
                    raise ValueError('旧公开内容与现有记录不一致')
            if apply:
                register_share(token, identity, descriptor, root=root)
                if read_shared_report(token, root=root) != page:
                    raise ValueError('动态读取结果与待迁移版本不一致')
                report['indexed'] += 1
            if remove_html:
                reject_symlinks(path)
                after = path.stat()
                if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                    raise ValueError('旧文件已变化，保留文件等待核验')
                path.unlink()
                report['removed_html'] += 1
                report['removed_bytes'] += before.st_size
            report['verified'] += 1
            report['eligible_bytes'] += before.st_size
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            report['errors'].append({'link_hash': hashlib.sha256(token.encode()).hexdigest()[:12], 'error': type(exc).__name__})
    report['unresolved'] = report['legacy_files'] - report['verified']
    return report
