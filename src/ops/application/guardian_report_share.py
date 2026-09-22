"""统一公开阅读入口：分享令牌定位数据，访问时使用共用模板渲染。"""
from contextlib import closing
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from src.shared.paths import data_dir
from src.ops.application.guardian_report_document import render_shared_document as render_shared_document
from src.ops.application.guardian_report_dashboard import render_guardian_dashboard
from src.ops.infrastructure.report_share_store import (
    TOKEN_PATTERN as TOKEN_PATTERN, database_locator, database_path, lookup_share,
    readonly_connection, register_share, reject_symlinks, validate_token,
)


def report_share_path(token: str, *, root: Path | None = None) -> Path:
    """Only for pre-migration files. No production publisher writes this path anymore."""
    validate_token(token)
    return (root or data_dir()) / 'shared_reports' / (token + '.html')


def render_report_share(period: str, day: str, result: dict) -> str:
    return render_guardian_dashboard(period, day, result)


def public_report_base_url() -> str:
    base = os.environ.get('LOCI_PUBLIC_BASE_URL', '').strip().rstrip('/')
    if not base:
        return ''
    parsed = urlsplit(base)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        raise ValueError('公开站点地址配置无效')
    return base


def guardian_reference(db_path: Path, period: str, day: str, result: dict, *, root: Path) -> dict:
    return {'version': 1, 'kind': 'guardian', 'database': database_locator(db_path, root),
            'period': period, 'day': day, 'revision': int(result.get('revision', 1)),
            'created_at': result.get('created_at', '')}


def load_guardian_reference(reference: dict, token: str, *, root: Path) -> dict | None:
    """Resolve the exact published revision in a read transaction, never today's account."""
    key = f"{reference['period']}:{reference['day']}"

    def matches(result: dict) -> bool:
        return (result.get('share_token') == token
                and int(result.get('revision', 1)) == reference['revision']
                and result.get('created_at', '') == reference['created_at'])

    with closing(readonly_connection(database_path(reference['database'], root))) as conn:
        conn.execute('BEGIN')
        current = conn.execute("SELECT result_json FROM guardian_reports WHERE report_key=? AND status='success'", (key,)).fetchone()
        if current:
            result = json.loads(current[0])
            if matches(result):
                return result
        # A correction moves the previous result (including its share token) here.
        old = conn.execute('SELECT result_json FROM guardian_report_revisions WHERE report_key=? AND revision=?',
                           (key, reference['revision'])).fetchone()
        if old:
            result = json.loads(old[0])
            if matches(result):
                return result
    return None


def publish_report_share(ledger, period: str, day: str, result: dict) -> str:
    base = public_report_base_url()
    if not base:
        return ''
    token = ledger.report_share_token(period, day, result.get('created_at', ''))
    # Caller-supplied presentation changes cannot overwrite the saved report content.
    saved = ledger.report(period, day)
    if not saved or saved['status'] != 'success' or saved['result'].get('share_token') != token:
        raise ValueError('报告已更新，请重新读取后分享')
    reference = guardian_reference(Path(ledger.db_path), period, day, saved['result'], root=data_dir())
    register_share(token, reference, reference, root=data_dir())
    return f'{base}/shared/reports/{token}'


def publish_document_share(token: str, identity: dict, document: dict) -> str:
    """Small public text survives diary pruning; raw run/tool/config data is not copied."""
    base = public_report_base_url()
    if not base:
        return ''
    # Whitelist the public view model, not arbitrary HTML or an entire run dictionary.
    allowed = {'sections', 'title', 'owner', 'created_at', 'revision'}
    if not isinstance(document, dict) or set(document) - allowed or 'sections' not in document:
        raise ValueError('公开报告只接受可读内容字段')
    descriptor = {'version': 1, 'kind': 'document', 'document': document}
    register_share(token, identity, descriptor, root=data_dir())
    return f'{base}/shared/reports/{token}'


def render_share_descriptor(token: str, descriptor: dict, *, root: Path) -> str | None:
    if not isinstance(descriptor, dict) or descriptor.get('version') != 1:
        raise ValueError('未知分享数据版本')
    if descriptor.get('kind') == 'guardian':
        result = load_guardian_reference(descriptor, token, root=root)
        return render_report_share(descriptor['period'], descriptor['day'], result) if result else None
    if descriptor.get('kind') == 'document':
        document = descriptor['document']
        return render_shared_document(document['sections'], title=document['title'], owner=document['owner'],
            created_at=document.get('created_at', ''), revision=document.get('revision', 1))
    raise ValueError('未知分享报告类型')


def read_shared_report(token: str, *, root: Path | None = None) -> str | None:
    """Public GET has no write side effects and no tenant selector supplied by the visitor."""
    root = root or data_dir()
    descriptor = lookup_share(token, root=root)
    if descriptor is not None:
        # Missing/removed source must not silently become a different report or stale HTML.
        return render_share_descriptor(token, descriptor, root=root)
    # Temporary compatibility for an old link not yet indexed by migrate_report_shares.
    # This only reads existing files. It never recreates a snapshot on cache miss.
    path = report_share_path(token, root=root)
    reject_symlinks(path)
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return None
