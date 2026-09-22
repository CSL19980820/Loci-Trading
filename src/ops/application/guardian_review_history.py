"""Tenant-bound, read-only report memory with explicit time and pagination boundaries."""
from __future__ import annotations

from copy import deepcopy
from contextlib import closing
from datetime import date, datetime, time
import json
from pathlib import Path
import sqlite3
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from src.shared.paths import palace_db
from src.shared.tenancy import current_tenant

REVIEW_HISTORY_TOOL = "guardian_review_history"
TZ = ZoneInfo("Asia/Shanghai")


class ReviewHistoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_key: str = Field(default="", description="指定报告编号时读取其完整所选字段；可先搜索目录")
    period: Literal["premarket", "daily", "weekly"] | None = None
    start_date: date | None = None
    end_date: date | None = None
    keyword: str = ""
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=50, description="单页报告数；next_read可继续，无总条数上限")
    include_details: bool = False
    fields: list[Literal["analysis", "facts", "tool_evidence"]] = Field(default_factory=lambda: ["analysis"])


class ReviewHistory:
    def __init__(self, *, palace_path: str | Path | None = None, as_of: str | None = None,
                 trade_date: str | None = None, exclude_key: str = "") -> None:
        self.path = Path(palace_path or palace_db()).resolve()
        self.tenant = current_tenant()
        now = datetime.fromisoformat(as_of) if as_of else datetime.now(TZ)
        now = now.replace(tzinfo=now.tzinfo or TZ).astimezone(TZ)
        if trade_date:
            now = min(now, datetime.combine(date.fromisoformat(trade_date), time.max, TZ))
        self.as_of = now.isoformat()
        self.day = now.date()
        self.exclude_key = exclude_key

    def schema(self, protocol: str) -> dict:
        from src.ai.application.tool_schema import tool_schema
        return tool_schema(protocol, REVIEW_HISTORY_TOOL,
            "只读查询当前租户的盘前、日复盘、周复盘和研究记忆；可跨周按日期、类型、关键词搜索。"
            "先读目录，再按report_key取完整analysis、facts或tool_evidence；按next_read续页。"
            "结果标明版本和生成时点，过期规则仅作历史依据，不恢复已停用策略。",
            ReviewHistoryQuery.model_json_schema())

    def read(self, arguments: dict[str, Any]) -> dict:
        if current_tenant() != self.tenant:
            return {"is_error": True, "text": "报告记忆不属于当前租户"}
        try:
            query = ReviewHistoryQuery.model_validate(arguments)
            start = query.start_date or date.min
            end = query.end_date or self.day
            if start > end or end > self.day:
                raise ValueError("查询区间无效或超出本轮报告时点")
            where = ["trade_date BETWEEN ? AND ?", "status='success'", "report_key<>?",
                     "julianday(COALESCE(json_extract(result_json,'$.created_at'),datetime(started,'unixepoch')))<=julianday(?)"]
            params: list[Any] = [start.isoformat(), end.isoformat(), self.exclude_key, self.as_of]
            if query.report_key:
                where.append("report_key=?"); params.append(query.report_key)
            if query.period:
                where.append("period=?"); params.append(query.period)
            if query.keyword:
                where.append("instr(lower(json_extract(result_json,'$.analysis')),lower(?))>0")
                params.append(query.keyword)
            fields = list(dict.fromkeys(query.fields))
            detail = bool(query.report_key or query.include_details)
            projections = ["report_key AS id", "period", "trade_date AS date",
                "json_extract(result_json,'$.created_at') AS created_at",
                "COALESCE(json_extract(result_json,'$.revision'),1) AS revision",
                "json_extract(result_json,'$.analysis.summary') AS summary"]
            if detail:
                # Field names are validated enums, never arbitrary SQL or file paths.
                projections += [f"json_extract(result_json,'$.{field}') AS {field}" for field in fields]
            clause = " AND ".join(where)
            with closing(sqlite3.connect(self.path.as_uri()+"?mode=ro", uri=True, timeout=5)) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only=ON")
                conn.execute("BEGIN")
                total = conn.execute(f"SELECT count(*) FROM guardian_reports WHERE {clause}", params).fetchone()[0]
                rows = conn.execute(f"SELECT {','.join(projections)} FROM guardian_reports WHERE {clause} "
                    "ORDER BY trade_date DESC,started DESC,report_key DESC LIMIT ? OFFSET ?",
                    [*params, query.limit, query.offset]).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                if detail:
                    for field in fields:
                        raw = item[field]
                        item[field] = json.loads(raw) if isinstance(raw, str) else raw
                from src.ops.application.guardian_memory import MEMORY_NOTE
                item['summary'] = deepcopy(item.get('summary'))
                if 'analysis' in item:
                    item['analysis'] = deepcopy(item['analysis'])
                item['current_use_note'] = MEMORY_NOTE
                items.append(item)
            next_offset = query.offset+len(items)
            continuation = query.model_dump(mode="json")
            continuation.update(offset=next_offset)
            result = {"as_of": self.as_of, "total": total, "items": items,
                "next_read": continuation if next_offset < total else None,
                "memory_semantics": "已保存的研究，不是交易指令。近期预载不代表全部记忆。"
                    "本查询仅返回时点前已生成的成功版本；晚于时点的更正版本不作为当时证据。"
                    "归档中的旧战法和旧观点只供复盘，不恢复任务或改写当前规则。"}
            if query.report_key and not items:
                return {"is_error": True, "text": json.dumps({**result, "error": "该报告无符合时点的可读成功版本"}, ensure_ascii=False)}
            return {"text": json.dumps(result, ensure_ascii=False)}
        except (ValueError, sqlite3.Error) as exc:
            return {"is_error": True, "text": f"报告记忆查询失败：{exc}"}
