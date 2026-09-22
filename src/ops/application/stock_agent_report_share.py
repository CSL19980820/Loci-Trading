"""独立智能体公开内容模型；与站内共用正文，不保存 HTML。"""
from src.ops.application.guardian_report_share import public_report_base_url, publish_document_share
from src.ops.infrastructure.report_share_store import database_locator
from src.shared.paths import data_dir
from src.ops.application.stock_agent_prompts import PHASE_NAMES
from src.ops.application.trading_report_content import trading_run_sections


def stock_agent_document(profile: dict, run: dict, brief: str) -> dict | None:
    detail = run['detail']
    summary = str(detail.get('summary') or run.get('summary') or '').strip()
    research = str(detail.get('research_plan') or '').strip()
    extra = any(detail.get(key) for key in ('decisions', 'fills', 'rejects', 'deferred', 'error'))
    if not (research and research != summary or extra or summary and summary != brief.strip()):
        return None
    sections = trading_run_sections(detail, summary=summary, status=run.get('status', ''))
    created = detail.get('as_of') or run.get('finished_at') or run['started_at']
    return {'sections': sections, 'title': f"{str(created)[:10]} · {PHASE_NAMES[run['phase']]}",
            'owner': profile['config']['name'], 'created_at': created}


def publish_stock_agent_share(ledger, agent_id: str, run_id: str, profile: dict, run: dict, brief: str) -> str:
    if not public_report_base_url():
        return ''
    saved = ledger.run_detail(agent_id, run_id)
    document = stock_agent_document(profile, saved, brief)
    if not document:
        return ''
    token = ledger.run_share_token(agent_id, run_id)
    identity = stock_agent_identity(ledger.db_path, agent_id, run_id, saved, root=data_dir())
    return publish_document_share(token, identity, document)


def stock_agent_identity(db_path, agent_id: str, run_id: str, run: dict, *, root) -> dict:
    return {'kind': 'stock_agent', 'database': database_locator(db_path, root),
            'agent_id': agent_id, 'run_id': run_id, 'started_at': run['started_at']}
