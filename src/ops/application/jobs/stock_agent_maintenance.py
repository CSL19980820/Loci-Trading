"""无模型调用的每租户日记维护；独立于智能体启停状态。"""
from src.ledger import GuardianDiaryStore, StockAgentStore


def execute_stock_agent_maintenance(config, context):
    context.check_cancelled()
    from src.ops.application.falcon_watch_pool import sync_falcon_watch_pools
    from src.shared.paths import palace_db
    resolved_palace = str(context.palace_db or palace_db())
    watch_sync = sync_falcon_watch_pools(context.ops_store, resolved_palace)
    context.check_cancelled()
    results = []
    with StockAgentStore(resolved_palace) as ledger:
        for profile in ledger.list_profiles(include_archived=True):
            context.check_cancelled()
            results.append({"agent_id": profile["id"], **ledger.prune_diary(profile["id"])})
    with GuardianDiaryStore(context.palace_db) as guardian:
        compacted = guardian.compact()
    return {"agents": results, "guardian": compacted, "falcon_watch_sync": watch_sync,
            "financial_records_deleted": 0}
