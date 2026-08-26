"""候选池可见性 SQL 片段。"""
from __future__ import annotations

#: 排除区间回填 / 历史重放（不要求 created_at 同日）
EXCLUDE_BACKFILL_SQL = (
    "IFNULL(source, '') NOT LIKE '%backfill%'",
    "IFNULL(source, '') NOT LIKE '%:history'",
)
# 旧版曾在启动时把过期 API 选股改写成 backfill；当前版本在读取时派生该口径，
# 避免为了展示过滤而改写审计事实。手工补录的历史记录不受影响。
EXCLUDE_STALE_API_SCREEN_SQL = (
    "(IFNULL(source, '') NOT LIKE 'api:screen%' OR substr("
    "REPLACE(IFNULL(created_at, ''), 'T', ' '), 1, 10) = occurred_on)"
)
#: 盘后真选：排除回填 + 写入日历日须等于选股日
LIVE_CANDIDATE_SQL = EXCLUDE_BACKFILL_SQL + (
    "substr(REPLACE(IFNULL(created_at, ''), 'T', ' '), 1, 10) = occurred_on",
)
