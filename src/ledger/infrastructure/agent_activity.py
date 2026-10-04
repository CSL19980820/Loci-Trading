"""首页研判聚合：只读当前租户，先选元数据再投影摘要，不逐个请求智能体历史。"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from src.shared.paths import palace_db

logger = logging.getLogger(__name__)
_TZ = ZoneInfo("Asia/Shanghai")
_PHASES = {"premarket": "盘前计划", "auction": "竞价研判", "intraday": "盘中研判",
           "closeout": "尾盘研判", "daily": "盘后复盘", "review": "盘后复盘", "weekly": "周复盘"}
_STATUSES = {"success": "已完成", "running": "正在研究", "failed": "运行失败", "cancelled": "已取消",
             "interrupted": "运行中断", "filled": "模拟成交", "recorded": "已记录", "rejected": "未执行"}


def activity_epoch(value: Any) -> float:
    """历史无时区时间按北京时间；兼容 guardian 秒时间戳和毫秒时间戳。"""
    try:
        if isinstance(value, (int, float)):
            number = float(value)
            return number / 1000 if abs(number) >= 1e12 else number
        text = str(value or "").strip()
        if not text:
            return 0.0
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=_TZ)
        return stamp.timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _iso(epoch: float) -> str:
    try:
        return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z") if epoch else ""
    except (ValueError, OverflowError, OSError):
        return ""


def _guardian_rows(conn: sqlite3.Connection, table: str, limit: int) -> list[dict[str, Any]]:
    report = table == "guardian_reports"
    key_column = "report_key" if report else "slot"
    extra = ", t.period" if report else ", 'intraday' AS period"
    # Table and column identifiers are internal constants. Only selected rows' JSON is inspected.
    sql = f"""WITH latest AS MATERIALIZED (
        SELECT {key_column} AS item_key, activity_epoch(started) AS epoch
        FROM {table} ORDER BY epoch DESC, {key_column} ASC LIMIT ?
    ), selected AS (
        SELECT f.*, t.status {extra}, CASE WHEN json_valid(t.result_json) THEN t.result_json ELSE '{{}}' END AS doc
        FROM latest f JOIN {table} t ON t.{key_column}=f.item_key
    ) SELECT item_key,epoch,status,period,
        substr(COALESCE(NULLIF(json_extract(doc,'$.error'),''),
                       NULLIF(json_extract(doc,'$.analysis.summary'),''),
                       CASE WHEN json_type(doc,'$.analysis')='text' THEN NULLIF(json_extract(doc,'$.analysis'),'') END,
                       NULLIF(json_extract(doc,'$.summary'),''),json_extract(doc,'$.body'),''),1,2000) AS summary,
        COALESCE(NULLIF(json_extract(doc,'$.error'),''),'') <> '' AS has_error
        FROM selected ORDER BY epoch DESC,item_key ASC"""
    out = []
    for raw in conn.execute(sql, (limit,)):
        row = dict(raw)
        status = str(row["status"] or "")
        out.append({"key": f"guardian:{'report' if report else 'run'}:{row['item_key']}",
                    "agentId": "guardian", "agentName": "天才交易员",
                    "to": "/agents/guardian?tab=" + ("reviews" if report else "research"),
                    "at": _iso(row["epoch"]), "phaseLabel": _PHASES.get(row["period"], "研判记录"),
                    "statusLabel": "研判中" if status == "running" else _STATUSES.get(status, "尚未运行"),
                    "summary": str(row["summary"] or "").strip(),
                    "failed": status in {"failed", "interrupted"} or bool(row["has_error"])})
    return out


def _stock_rows(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute("""WITH latest AS MATERIALIZED (
        SELECT r.id, r.agent_id, COALESCE(NULLIF(activity_epoch(r.started_at),0),activity_epoch(r.finished_at)) AS epoch
        FROM stock_agent_runs r JOIN stock_agent_profiles p ON p.id=r.agent_id
        WHERE p.archived=0 ORDER BY epoch DESC, r.agent_id ASC, r.id ASC LIMIT ?
    ) SELECT f.id, f.agent_id,f.epoch,r.phase,r.status,substr(r.summary,1,2000) AS summary,
        substr(COALESCE(NULLIF(json_extract(CASE WHEN json_valid(p.config_json) THEN p.config_json ELSE '{}' END,'$.name'),''),p.id),1,200) AS name
        FROM latest f JOIN stock_agent_runs r ON r.id=f.id JOIN stock_agent_profiles p ON p.id=f.agent_id
        ORDER BY f.epoch DESC,f.agent_id,f.id""", (limit,))
    return [{"key": f"{row['agent_id']}:{row['id']}", "agentId": row["agent_id"], "agentName": row["name"],
             "to": f"/agents/{quote(row['agent_id'], safe='')}?tab=diary", "at": _iso(row["epoch"]),
             "phaseLabel": _PHASES.get(row["phase"], "研判记录"),
             "statusLabel": _STATUSES.get(row["status"], "尚未运行"),
             "summary": str(row["summary"] or "").strip(), "failed": row["status"] in {"failed", "interrupted"}}
            for row in rows]


def read_agent_activity(*, limit: int = 16, db_path: Path | str | None = None) -> dict[str, Any]:
    """三类历史各取至多 N 条，再统一排序截断；从不加载完整账户、模型上下文或密钥。"""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("研判条数须在1至50之间")
    path = Path(db_path or palace_db())
    if not path.exists():
        return {"items": [], "partial_errors": []}
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    successful_queries = 0
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)) as conn:
        conn.row_factory = sqlite3.Row
        conn.create_function("activity_epoch", 1, activity_epoch, deterministic=True)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        queries = [("guardian_cycles", "盘中研判", lambda: _guardian_rows(conn, "guardian_cycles", limit)),
                   ("guardian_reports", "阶段报告", lambda: _guardian_rows(conn, "guardian_reports", limit)),
                   ("stock_agent_runs", "股票智能体研判", lambda: _stock_rows(conn, limit))]
        for table, label, loader in queries:
            if table not in tables:
                continue
            try:
                items.extend(loader())
                successful_queries += 1
            except sqlite3.Error:
                logger.warning("首页%s读取失败", label, exc_info=True)
                errors.append(f"{label}暂时不可用")
        if errors and not successful_queries:
            raise sqlite3.OperationalError("研判聚合读取失败")
    items.sort(key=lambda row: (-activity_epoch(row["at"]), row["key"]))
    return {"items": items[:limit], "partial_errors": errors}
