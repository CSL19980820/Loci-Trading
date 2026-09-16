"""无模型调用的每租户日记维护；独立于智能体启停状态。"""
from src.ledger import GuardianDiaryStore, StockAgentStore


def execute_stock_agent_maintenance(config, context):
    context.check_cancelled()
    results = []
    with StockAgentStore(context.palace_db) as ledger:
        for profile in ledger.list_profiles(include_archived=True):
            context.check_cancelled()
            results.append({"agent_id": profile["id"], **ledger.prune_diary(profile["id"])})
    with GuardianDiaryStore(context.palace_db) as guardian:
        compacted = guardian.compact()
    return {"agents": results, "guardian": compacted, "financial_records_deleted": 0}
