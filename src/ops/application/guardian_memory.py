"""共享的研究材料说明。"""

from datetime import datetime, timezone

MEMORY_NOTE = "研究材料和条件计划供当前判断参考；事实、成交及工具证据保留原始时点和口径。"


def current_research(record: dict, state: dict) -> bool:
    """重置前的研究只留在历史查询中；缺失时间的旧材料不自动回流。"""
    cutoff = state.get('research_reset_at')
    if not cutoff:
        return True
    result = record.get('result') or record
    raw = result.get('created_at') or result.get('as_of') or record.get('slot')
    try:
        stamp = (datetime.fromisoformat(str(raw)) if raw else
                 datetime.fromtimestamp(float(record['started']), timezone.utc))
        return stamp.replace(tzinfo=stamp.tzinfo or timezone.utc) >= datetime.fromisoformat(cutoff)
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return False
